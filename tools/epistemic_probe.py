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
from collections import Counter, defaultdict
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


BASELINES: Dict[str, Callable[..., dict]] = {
    "uniform": baseline_uniform,
    "prior_anchored": baseline_prior_anchored,
    "seductive": baseline_seductive,
    "overcautious": baseline_overcautious,
    "narrative_match": baseline_narrative_match,
    "calibrated": baseline_calibrated,
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
    """Wilson score interval for binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    lower = (center - adj) / denom
    upper = (center + adj) / denom
    return (max(0.0, lower), min(1.0, upper))


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
    # Pair key = identical instance except framing: (scenario,evidence,prior,presentation,seed,replication)
    # This is the matched sibling design from test_bare_table_vs_narrative_matched_siblings.
    pair_dict: Dict[Tuple, Dict[str, int]] = defaultdict(dict)  # pair_key -> framing -> pass 0/1
    # For pooled stats and variance separation: group_key = (scenario,evidence,prior)
    grouped_pooled: Dict[Tuple, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    # For seed variance: group_key -> framing -> seed -> list of pass indicators (over presentation,replication)
    per_seed: Dict[Tuple, Dict[str, Dict[int, List[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # For replication variance: group_key -> framing -> (seed,presentation) -> list of pass over replications
    per_instance_repl: Dict[Tuple, Dict[str, Dict[Tuple[int, str], List[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for r in rows:
        group_key = (r["scenario"], r["evidence"], r["prior"])
        pair_key = (r["scenario"], r["evidence"], r["prior"], r["presentation"], r["seed"], r["replication"])
        is_pass = 1 if r["failure_mode"] == "pass" else 0
        pair_dict[pair_key][r["framing"]] = is_pass
        grouped_pooled[group_key][r["framing"]].append(is_pass)
        per_seed[group_key][r["framing"]][r["seed"]].append(is_pass)
        per_instance_repl[group_key][r["framing"]][(r["seed"], r["presentation"])].append(is_pass)

    print("\n--- Narrative vs Bare-Table delta (paired by scenario,evidence,prior,presentation,seed,replication) ---")
    print("Pooled Wilson 95% CI on pass count; paired d = pass_narr - pass_bare ∈ {-1,0,+1}")
    print("Discordant: bare_only = (narr fail, bare pass) = seduction effect; narr_only = (narr pass, bare fail)")
    print("Seed variance = std of per-seed means; Repl variance = mean within-instance std across replications\n")

    overall_pairs = []
    overall_d = []
    overall_bare_only = 0
    overall_narr_only = 0

    for gkey in sorted(grouped_pooled):
        scen, ev, prior = gkey
        narr_vals = grouped_pooled[gkey].get("narrative", [])
        bare_vals = grouped_pooled[gkey].get("bare_table", [])

        # Pooled Wilson
        def pooled_stats(vals: List[int]):
            k = sum(vals)
            n = len(vals)
            lo, hi = wilson_interval(k, n)
            return k, n, lo, hi

        k_narr, n_narr, lo_narr, hi_narr = pooled_stats(narr_vals)
        k_bare, n_bare, lo_bare, hi_bare = pooled_stats(bare_vals)

        # Seed variance and replication variance per framing
        def variance_stats(framing: str):
            # per-seed means
            seed_means = []
            for seed, v in per_seed[gkey][framing].items():
                if v:
                    seed_means.append(sum(v) / len(v))
            _, seed_std = mean_std(seed_means)
            # replication variance: for each (seed,presentation), std across replications
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

        # Paired stats: collect pairs belonging to this group_key
        d_list = []
        both_pass = both_fail = narr_only = bare_only = 0
        for pair_key, framings in pair_dict.items():
            if pair_key[0] != scen or pair_key[1] != ev or pair_key[2] != prior:
                continue
            if "narrative" not in framings or "bare_table" not in framings:
                continue
            pn = framings["narrative"]
            pb = framings["bare_table"]
            d = pn - pb
            d_list.append(d)
            if pn == 1 and pb == 1:
                both_pass += 1
            elif pn == 0 and pb == 0:
                both_fail += 1
            elif pn == 1 and pb == 0:
                narr_only += 1
            else:
                bare_only += 1

        n_pairs = len(d_list)
        if n_pairs:
            mean_d, std_d = mean_std(d_list)
            se_d = std_d / math.sqrt(n_pairs) if n_pairs > 1 else 0.0
            ci_low = mean_d - 1.96 * se_d
            ci_high = mean_d + 1.96 * se_d
            # McNemar (without continuity correction, as in fable note; report with correction note)
            discordant = narr_only + bare_only
            if discordant > 0:
                chi2 = (narr_only - bare_only) ** 2 / discordant
                # with continuity correction: (|b-c|-1)^2/(b+c)
                chi2_cc = (abs(narr_only - bare_only) - 1) ** 2 / discordant if discordant > 0 else 0.0
            else:
                chi2 = 0.0
                chi2_cc = 0.0
        else:
            mean_d = std_d = se_d = ci_low = ci_high = chi2 = chi2_cc = 0.0

        overall_pairs.extend([gkey] * n_pairs)
        overall_d.extend(d_list)
        overall_bare_only += bare_only
        overall_narr_only += narr_only

        print(
            f"{scen},{ev},{prior}: n_pairs={n_pairs}\n"
            f"  pooled: narr {k_narr}/{n_narr} [{lo_narr:.2f},{hi_narr:.2f}] "
            f"(seed_std={seed_std_narr:.2f} n_seed={n_seed_narr} repl_std={repl_std_narr:.2f}) | "
            f"bare {k_bare}/{n_bare} [{lo_bare:.2f},{hi_bare:.2f}] "
            f"(seed_std={seed_std_bare:.2f} n_seed={n_seed_bare} repl_std={repl_std_bare:.2f})\n"
            f"  paired: d=pass_narr-pass_bare mean={mean_d:+.2f} [{ci_low:+.2f},{ci_high:+.2f}] "
            f"std={std_d:.2f} | both_pass={both_pass} both_fail={both_fail} "
            f"narr_only={narr_only} bare_only={bare_only} (seduction) "
            f"McNemar χ²={chi2:.2f} (cc={chi2_cc:.2f})"
        )

    # Overall summary
    if overall_d:
        mean_d_all, std_d_all = mean_std(overall_d)
        se_all = std_d_all / math.sqrt(len(overall_d)) if len(overall_d) > 1 else 0.0
        ci_low_all = mean_d_all - 1.96 * se_all
        ci_high_all = mean_d_all + 1.96 * se_all
        discordant_all = overall_narr_only + overall_bare_only
        chi2_all = (overall_narr_only - overall_bare_only) ** 2 / discordant_all if discordant_all else 0.0
        print(
            f"\nOverall: n_pairs={len(overall_d)} mean_d={mean_d_all:+.3f} "
            f"[{ci_low_all:+.3f},{ci_high_all:+.3f}] "
            f"bare_only (narr fail,bare pass)={overall_bare_only} "
            f"narr_only={overall_narr_only} χ²={chi2_all:.2f}"
        )

    if args.output:
        print(f"\nreport: {args.output}")


if __name__ == "__main__":
    main()
