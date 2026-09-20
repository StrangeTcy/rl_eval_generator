#!/usr/bin/env python3
"""Probe tool for the epistemic_games family (development loop).

The generator is completely model-independent; this tool is where any
answer source plugs in, per the development workflow:

    instance -> latent game -> observations -> required inference -> verifiable answer

It builds instances symbolically, feeds each one's PUBLIC information to an
answer function, grades the answer with the same core the judge uses, and
emits a structural failure-mode report - "which epistemic failure modes does
this answer source exhibit?" - instead of a bare accuracy number.

Answer sources
--------------
Built-in fixed heuristics (baselines), each a pure function of the public
task information (they never see the ground truth):

  calibrated     sanity upper bound - the ground truth (NOT public-only)
  uniform        always (0.5, indistinguishable, neither)
  prior_anchored answers the prior, verdict indistinguishable
  seductive      "they said it, so they must be the genuine type"
  overcautious   "if it is this clean, they must be strategic"
  narrative_match matches the transcript to the world whose narrative fits
  framing_sensitive  oracle on bare_table, seductive on narrative (positive control)

External answer sources (e.g. a cheap model such as Atria, or a frontier
model later):

    python tools/epistemic_probe.py --module my_answers.py:answer_fn

where ``answer_fn(public: dict) -> dict`` takes the public task information
(the same content a model sees in task.md) and returns an answer dict with
keys posterior_world1 / verdict / most_supported / justification. The probe
never needs any model access of its own.

Usage
----
    python tools/epistemic_probe.py --baseline seductive --seeds 5
    python tools/epistemic_probe.py --baseline calibrated --seeds 3 --output report.jsonl
    python tools/epistemic_probe.py --module my_answers.py:answer_fn --seeds 5 --replications 3
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "envs" / "epistemic_games" / "files" / "core.py"

SCENARIOS = ("trap", "report")
EVIDENCE = ("ambiguous", "weak", "strong")
PRIORS = ("balanced", "skewed")
PRESENTATIONS = ("solo", "paired")
FRAMINGS = ("narrative", "bare_table")

PASS_THRESHOLD = 0.85


def load_core():
    spec = importlib.util.spec_from_file_location("epg_probe_core", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["epg_probe_core"] = module
    spec.loader.exec_module(module)
    return module


CORE = load_core()


def public_info(instance) -> dict:
    """Everything the answer source is allowed to see (mirrors task.md)."""
    return {
        "family": "epistemic_games",
        "subfamily": instance.subfamily,
        "template": instance.template,
        "presentation": instance.presentation,
        "framing": instance.framing,
        "scenario_text": instance.public_task_md(),
        "prior_world1": float(instance.prior1),
        "actions": {
            "denial": instance.vocab.denial_text,
            "vague": instance.vocab.vague_text,
        },
        "behavior": {
            "world1": {a: float(p) for a, p in instance.hypotheses["world1"].behavior.items()},
            "world2": {a: float(p) for a, p in instance.hypotheses["world2"].behavior.items()},
        },
        "observation": instance.observation,
        "observation_text": instance.action_text(instance.observation),
        "verdicts": CORE.VERDICTS,
        "support_options": CORE.SUPPORT_OPTIONS,
    }


def make_answer(public: dict, posterior, verdict, support, why: str) -> dict:
    return {
        "posterior_world1": posterior,
        "verdict": verdict,
        "most_supported": support,
        "justification": why,
    }


def baseline_uniform(public: dict) -> dict:
    return make_answer(public, 0.5, "indistinguishable", "neither", "no view")


def baseline_prior_anchored(public: dict) -> dict:
    p1 = public["prior_world1"]
    support = "world1" if p1 > 0.5 else "world2" if p1 < 0.5 else "neither"
    return make_answer(public, p1, "indistinguishable", support, "prior only")


def baseline_seductive(public: dict) -> dict:
    if public["observation"] == "denial":
        return make_answer(public, 0.8, "distinguishable", "world1",
                           "a direct denial is what a genuine player says")
    return make_answer(public, 0.3, "distinguishable", "world2",
                       "evasiveness reeks of strategy")


def baseline_overcautious(public: dict) -> dict:
    if public["observation"] == "denial":
        return make_answer(public, 0.2, "distinguishable", "world2",
                           "a perfect denial is the strategic player's tell")
    return make_answer(public, 0.7, "distinguishable", "world1",
                       "vagueness is what a flustered genuine player does")


def baseline_narrative_match(public: dict) -> dict:
    if public["observation"] == "denial":
        return make_answer(public, 0.65, "weakly_distinguishable", "world1",
                           "the transcript fits world 1's story")
    return make_answer(public, 0.35, "weakly_distinguishable", "world2",
                       "the transcript fits world 2's story")


def baseline_calibrated(public: dict, hidden) -> dict:
    return CORE.ground_truth_answer(hidden)


def oracle_from_public(public: dict) -> dict:
    """Public-only oracle: recompute posterior/verdict from behavior tables."""
    p1 = public["prior_world1"]
    obs = public["observation"]
    b1 = public["behavior"]["world1"][obs]
    b2 = public["behavior"]["world2"][obs]
    denom = b1 * p1 + b2 * (1 - p1)
    post = b1 * p1 / denom if denom != 0 else 0.5
    # likelihood ratio
    if b1 == 0 or b2 == 0:
        ratio = float('inf') if b1 != b2 else 1.0
    else:
        ratio = max(b1 / b2, b2 / b1)
    if abs(ratio - 1.0) < 1e-9:
        verdict = "indistinguishable"
    elif ratio < 3:
        verdict = "weakly_distinguishable"
    else:
        verdict = "distinguishable"
    if post > 0.5 + 1e-9:
        support = "world1"
    elif post < 0.5 - 1e-9:
        support = "world2"
    else:
        support = "neither"
    return make_answer(public, post, verdict, support, "oracle from public")


def baseline_framing_sensitive(public: dict) -> dict:
    """Positive control: oracle on bare_table, seductive on narrative."""
    if public["framing"] == "bare_table":
        return oracle_from_public(public)
    return baseline_seductive(public)


BASELINES: Dict[str, Callable[..., dict]] = {
    "uniform": baseline_uniform,
    "prior_anchored": baseline_prior_anchored,
    "seductive": baseline_seductive,
    "overcautious": baseline_overcautious,
    "narrative_match": baseline_narrative_match,
    "calibrated": baseline_calibrated,
    "framing_sensitive": baseline_framing_sensitive,
}


def load_external_answer_fn(module_spec: str) -> Callable[[dict], dict]:
    path_str, _, fn_name = module_spec.partition(":")
    if not fn_name:
        raise SystemExit("--module must be path.py:function_name")
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    spec = importlib.util.spec_from_file_location("epg_probe_answers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["epg_probe_answers"] = module
    spec.loader.exec_module(module)
    fn = getattr(module, fn_name, None)
    if not callable(fn):
        raise SystemExit(f"callable {fn_name!r} not found in {path}")
    return fn


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for binomial proportion. Handles k=0 correctly."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    lower = (center - adj) / denom
    upper = (center + adj) / denom
    return (max(0.0, lower), min(1.0, upper))


def exact_mcnemar_p(bare_only: int, narr_only: int) -> float | None:
    """Exact two-sided binomial test for McNemar on discordant pairs.

    Under H0, conditional on discordant pairs, bare_only ~ Bin(n_discordant, 0.5).
    Returns p-value, or None if discordant=0 (undefined, not zero).
    """
    n = bare_only + narr_only
    if n == 0:
        return None
    # Two-sided: sum of probabilities at least as extreme as observed
    # Observed deviation from n/2
    b = bare_only
    # Use min tail
    k = min(b, n - b)
    prob = 0.0
    for i in range(k + 1):
        prob += math.comb(n, i) / (2 ** n)
    p_two = min(1.0, 2 * prob)
    # When b == n/2 and n even, prob includes half mass + middle term, doubling would exceed 1
    # but capped at 1, which is correct for exact two-sided (p=1 when perfectly balanced)
    return p_two


def newcombe_paired_diff_interval(b: int, c: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Newcombe-style interval for paired difference (b-c)/n.

    Uses Wilson intervals for b/n and c/n (method analogous to Newcombe 1998 for
    difference of proportions). Handles b=c=0 correctly: interval is
    [-Wilson(0/n).upper, +Wilson(0/n).upper] not [0,0].
    """
    if n == 0:
        return (0.0, 0.0)
    pb = b / n
    pc = c / n
    diff = pb - pc  # note: b=narr_only, c=bare_only => diff = (narr_only-bare_only)/n
    # Wilson intervals for each discordant proportion
    lb, ub = wilson_interval(b, n, z=z)
    lc, uc = wilson_interval(c, n, z=z)
    # Lower = diff - sqrt((pb-lb)^2 + (uc-pc)^2)
    # Upper = diff + sqrt((ub-pb)^2 + (pc-lc)^2)
    lower = diff - math.sqrt((pb - lb) ** 2 + (uc - pc) ** 2)
    upper = diff + math.sqrt((ub - pb) ** 2 + (pc - lc) ** 2)
    return (lower, upper)


def mean_std(vals: List[float]) -> Tuple[float, float]:
    if not vals:
        return 0.0, 0.0
    m = sum(vals) / len(vals)
    if len(vals) > 1:
        var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
        return m, math.sqrt(var)
    return m, 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", choices=sorted(BASELINES),
                        help="built-in fixed answer source")
    parser.add_argument("--module", default="",
                        help="external answer source: path.py:function_name(public)->dict")
    parser.add_argument("--seeds", type=int, default=5,
                        help="seeds per axis combination (0..seeds-1)")
    parser.add_argument("--replications", type=int, default=1,
                        help="replications per instance (for temperature>0 models). "
                             "Keeps instance/seed variance separate from API replication variance.")
    parser.add_argument("--output", default="",
                        help="optional JSONL report path")
    args = parser.parse_args()

    if bool(args.baseline) == bool(args.module):
        parser.error("exactly one of --baseline or --module is required")
    if args.replications < 1:
        parser.error("--replications must be >=1")

    if args.baseline:
        answer_fn = BASELINES[args.baseline]
        name = args.baseline
    else:
        answer_fn = load_external_answer_fn(args.module)
        name = args.module

    out = open(args.output, "w", encoding="utf-8") if args.output else None
    rows: List[dict] = []
    try:
        for scenario, evidence, presentation, prior, framing in itertools.product(
            SCENARIOS, EVIDENCE, PRESENTATIONS, PRIORS, FRAMINGS
        ):
            for seed in range(max(args.seeds, 1)):
                for repl in range(args.replications):
                    instance = CORE.build_instance(scenario, evidence, prior, presentation, seed, framing=framing)
                    public = public_info(instance)
                    if args.baseline == "calibrated":
                        answer = answer_fn(public, instance)
                    else:
                        answer = answer_fn(public)
                    grading = instance.grade(answer, pass_threshold=PASS_THRESHOLD)
                    row = {
                        "answer_source": name,
                        "scenario": scenario,
                        "evidence": evidence,
                        "presentation": presentation,
                        "prior": prior,
                        "framing": framing,
                        "seed": seed,
                        "replication": repl,
                        "observation": instance.observation,
                        "failure_mode": grading["failure_mode"],
                        "score": grading["metrics"]["score"],
                        "posterior_reported": grading["metrics"].get("posterior_reported"),
                        "posterior_true": grading["metrics"]["posterior_true"],
                        "verdict_reported": grading["metrics"].get("verdict_reported"),
                        "verdict_true": grading["metrics"]["verdict_true"],
                        "justification": answer.get("justification")
                        if isinstance(answer, dict) else None,
                    }
                    rows.append(row)
                    if out is not None:
                        out.write(json.dumps(row) + "\n")
    finally:
        if out is not None:
            out.close()

    # Structural diagnosis: failure mode x evidence level.
    modes: Dict[str, Dict[str, int]] = {}
    for row in rows:
        modes.setdefault(row["failure_mode"], dict.fromkeys(EVIDENCE, 0))
        modes[row["failure_mode"]][row["evidence"]] += 1

    print(f"\nepistemic_games probe: answer_source={name} instances={len(rows)} "
          f"(seeds={args.seeds} replications={args.replications})\n")
    header = f"{'failure_mode':<28} {'ambiguous':>10} {'weak':>8} {'strong':>8} {'total':>8}"
    print(header)
    print("-" * len(header))
    for mode in sorted(modes, key=lambda m: (-sum(modes[m].values()), m)):
        counts = modes[mode]
        print(f"{mode:<28} {counts['ambiguous']:>10} {counts['weak']:>8} {counts['strong']:>8} "
              f"{sum(counts.values()):>8}")
    passed = sum(1 for r in rows if r["failure_mode"] == "pass")
    print(f"\npass: {passed}/{len(rows)}")

    # --- Paired framing analysis ---
    # Pairing is on instance (shared prior/likelihoods/observation), not on replication draw.
    # instance_key = (scenario,evidence,prior,presentation,seed) — same Bayes problem
    # For each instance, average pass rate over replications per framing, then d_i = p_narr - p_bare
    # This averages out replication noise within each side before differencing.
    instance_dict: Dict[Tuple, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    # For pooled stats: group_key = (scenario,evidence,prior) -> framing -> list of pass indicators (over all replications)
    grouped_pooled: Dict[Tuple, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    # For seed variance: group_key -> framing -> seed -> list of pass (over presentation,replication)
    per_seed: Dict[Tuple, Dict[str, Dict[int, List[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # For replication variance: group_key -> framing -> (seed,presentation) -> list over replications
    per_instance_repl: Dict[Tuple, Dict[str, Dict[Tuple[int, str], List[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for r in rows:
        group_key = (r["scenario"], r["evidence"], r["prior"])
        inst_key = (r["scenario"], r["evidence"], r["prior"], r["presentation"], r["seed"])
        is_pass = 1 if r["failure_mode"] == "pass" else 0
        instance_dict[inst_key][r["framing"]].append(is_pass)
        grouped_pooled[group_key][r["framing"]].append(is_pass)
        per_seed[group_key][r["framing"]][r["seed"]].append(is_pass)
        per_instance_repl[group_key][r["framing"]][(r["seed"], r["presentation"])].append(is_pass)

    print("\n--- Narrative vs Bare-Table delta (paired by instance: scenario,evidence,prior,presentation,seed) ---")
    print("Pooled Wilson 95% CI on pass count; paired d_i = p̄_narr,i − p̄_bare,i averaged over replications")
    print("Seduction rate = bare_only / n_pairs (narr fail, bare pass) with Wilson CI; handles 0/10 → [0.00,0.28]")
    print("Exact McNemar p = exact binomial on discordant pairs; NA when b+c=0 (undefined, not zero)")
    print("Newcombe paired-diff CI uses Wilson intervals for discordant proportions")
    print("Seed variance = std of per-seed means; Repl variance = mean within-instance std across replications\n")

    overall_d: List[float] = []
    overall_bare_only = 0
    overall_narr_only = 0
    overall_pairs = 0

    for gkey in sorted(grouped_pooled):
        scen, ev, prior = gkey
        narr_vals = grouped_pooled[gkey].get("narrative", [])
        bare_vals = grouped_pooled[gkey].get("bare_table", [])

        def pooled_stats(vals: List[int]):
            k = sum(vals)
            n = len(vals)
            lo, hi = wilson_interval(k, n)
            return k, n, lo, hi

        k_narr, n_narr, lo_narr, hi_narr = pooled_stats(narr_vals)
        k_bare, n_bare, lo_bare, hi_bare = pooled_stats(bare_vals)

        def variance_stats(framing: str):
            seed_means = []
            for seed, v in per_seed[gkey][framing].items():
                if v:
                    seed_means.append(sum(v) / len(v))
            _, seed_std = mean_std(seed_means)
            repl_stds = []
            for inst_key, v in per_instance_repl[gkey][framing].items():
                if len(v) > 1:
                    m = sum(v) / len(v)
                    var = sum((x - m) ** 2 for x in v) / (len(v) - 1) if len(v) > 1 else 0.0
                    repl_stds.append(math.sqrt(var))
            repl_std_mean = sum(repl_stds) / len(repl_stds) if repl_stds else 0.0
            return seed_std, repl_std_mean, len(seed_means)

        seed_std_narr, repl_std_narr, n_seed_narr = variance_stats("narrative")
        seed_std_bare, repl_std_bare, n_seed_bare = variance_stats("bare_table")

        # Paired on instance, averaging over replications
        d_list: List[float] = []
        both_pass = both_fail = narr_only = bare_only = 0
        # For deterministic case, d_list values are in {-1,0,+1}
        for inst_key in sorted(instance_dict):
            if inst_key[0] != scen or inst_key[1] != ev or inst_key[2] != prior:
                continue
            framings = instance_dict[inst_key]
            if "narrative" not in framings or "bare_table" not in framings:
                continue
            # Average over replications per framing
            p_narr = sum(framings["narrative"]) / len(framings["narrative"]) if framings["narrative"] else 0.0
            p_bare = sum(framings["bare_table"]) / len(framings["bare_table"]) if framings["bare_table"] else 0.0
            d_i = p_narr - p_bare
            d_list.append(d_i)

            # Discordance counts: for deterministic case, exact; for stochastic, count by sign of d_i
            # Keep both_pass/both_fail for exact 0/1 case, otherwise use thresholded sign
            if abs(p_narr - 1.0) < 1e-9 and abs(p_bare - 1.0) < 1e-9:
                both_pass += 1
            elif abs(p_narr) < 1e-9 and abs(p_bare) < 1e-9:
                both_fail += 1
            elif d_i > 1e-9:
                narr_only += 1
            elif d_i < -1e-9:
                bare_only += 1
            else:
                # d_i == 0 but not both 0/1 (e.g., both 0.5) — treat as tie, not discordant
                pass

        n_pairs = len(d_list)
        if n_pairs:
            mean_d, std_d = mean_std(d_list)
            # Newcombe paired-diff interval using b=narr_only, c=bare_only
            # Note: diff = (narr_only - bare_only)/n for deterministic, but for continuous d_i
            # mean_d may differ slightly from (narr_only-bare_only)/n when p are fractional.
            # We report both: mean_d and Newcombe interval for discordant counts.
            newcombe_lo, newcombe_hi = newcombe_paired_diff_interval(narr_only, bare_only, n_pairs)
            # Wilson intervals for seduction rates
            lo_bare_only, hi_bare_only = wilson_interval(bare_only, n_pairs)
            lo_narr_only, hi_narr_only = wilson_interval(narr_only, n_pairs)
            # Exact McNemar p
            p_exact = exact_mcnemar_p(bare_only, narr_only)
            # McNemar chi2 approximations (for reference, unreliable <25 discordant)
            discordant = narr_only + bare_only
            if discordant > 0:
                chi2 = (narr_only - bare_only) ** 2 / discordant
                chi2_cc = (abs(narr_only - bare_only) - 1) ** 2 / discordant
            else:
                chi2 = None
                chi2_cc = None
        else:
            mean_d = std_d = 0.0
            newcombe_lo = newcombe_hi = 0.0
            lo_bare_only = hi_bare_only = lo_narr_only = hi_narr_only = 0.0
            p_exact = None
            chi2 = chi2_cc = None

        overall_d.extend(d_list)
        overall_bare_only += bare_only
        overall_narr_only += narr_only
        overall_pairs += n_pairs

        chi2_str = f"{chi2:.2f}" if chi2 is not None else "NA"
        chi2_cc_str = f"{chi2_cc:.2f}" if chi2_cc is not None else "NA"
        p_str = f"{p_exact:.4f}" if p_exact is not None else "NA"

        print(
            f"{scen},{ev},{prior}: n_pairs={n_pairs} (instances, averaged over {args.replications} repl)\n"
            f"  pooled: narr {k_narr}/{n_narr} [{lo_narr:.2f},{hi_narr:.2f}] "
            f"(seed_std={seed_std_narr:.2f} n_seed={n_seed_narr} repl_std={repl_std_narr:.2f}) | "
            f"bare {k_bare}/{n_bare} [{lo_bare:.2f},{hi_bare:.2f}] "
            f"(seed_std={seed_std_bare:.2f} n_seed={n_seed_bare} repl_std={repl_std_bare:.2f})\n"
            f"  paired: mean d_i={mean_d:+.3f} std={std_d:.3f} Newcombe diff CI [{newcombe_lo:+.2f},{newcombe_hi:+.2f}] "
            f"(diff=narr_only-bare_only)\n"
            f"    discordant: both_pass={both_pass} both_fail={both_fail} "
            f"narr_only={narr_only} [{lo_narr_only:.2f},{hi_narr_only:.2f}] "
            f"bare_only={bare_only} (seduction) [{lo_bare_only:.2f},{hi_bare_only:.2f}] "
            f"McNemar χ²={chi2_str} (cc={chi2_cc_str}) exact p={p_str}"
        )

    if overall_d:
        mean_d_all, std_d_all = mean_std(overall_d)
        newcombe_lo_all, newcombe_hi_all = newcombe_paired_diff_interval(
            overall_narr_only, overall_bare_only, overall_pairs
        )
        lo_bare_all, hi_bare_all = wilson_interval(overall_bare_only, overall_pairs)
        p_all = exact_mcnemar_p(overall_bare_only, overall_narr_only)
        chi2_all = (overall_narr_only - overall_bare_only) ** 2 / (overall_narr_only + overall_bare_only) if (overall_narr_only + overall_bare_only) > 0 else None
        chi2_all_str = f"{chi2_all:.2f}" if chi2_all is not None else "NA"
        p_all_str = f"{p_all:.4f}" if p_all is not None else "NA"
        print(
            f"\nOverall: n_pairs={overall_pairs} mean_d={mean_d_all:+.3f} "
            f"Newcombe [{newcombe_lo_all:+.3f},{newcombe_hi_all:+.3f}] "
            f"bare_only (seduction)={overall_bare_only}/{overall_pairs} [{lo_bare_all:.2f},{hi_bare_all:.2f}] "
            f"narr_only={overall_narr_only} χ²={chi2_all_str} exact p={p_all_str}"
        )

    if args.output:
        print(f"\nreport: {args.output}")


if __name__ == "__main__":
    main()
