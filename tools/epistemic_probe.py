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
  framing_sensitive_q10/q20/q30  graded controls: oracle on bare, narrative = seductive with prob q else oracle (power check)

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
import random
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
        "seed": instance.seed,
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


def make_graded_framing_sensitive(q: float):
    """Graded positive control: oracle on bare, narrative = seductive with prob q else oracle.

    q in {0.1,0.2,0.3} gives power check — minimum detectable effect at planned seed count.
    Deterministic per instance: uses hashlib of scenario_text+seed+presentation to get uniform [0,1).
    """
    import hashlib

    def baseline(public: dict) -> dict:
        if public["framing"] == "bare_table":
            return oracle_from_public(public)
        txt = public.get("scenario_text", "")[:500] + f"|{public.get('seed',0)}|{public.get('presentation','')}"
        h = hashlib.md5(txt.encode()).hexdigest()
        # Use first 8 hex chars as int
        r = (int(h[:8], 16) % 10000) / 10000.0
        if r < q:
            return baseline_seductive(public)
        return oracle_from_public(public)
    baseline.__name__ = f"baseline_framing_sensitive_q{int(q*100)}"
    return baseline


BASELINES: Dict[str, Callable[..., dict]] = {
    "uniform": baseline_uniform,
    "prior_anchored": baseline_prior_anchored,
    "seductive": baseline_seductive,
    "overcautious": baseline_overcautious,
    "narrative_match": baseline_narrative_match,
    "calibrated": baseline_calibrated,
    "framing_sensitive": baseline_framing_sensitive,
    "framing_sensitive_q10": make_graded_framing_sensitive(0.10),
    "framing_sensitive_q20": make_graded_framing_sensitive(0.20),
    "framing_sensitive_q30": make_graded_framing_sensitive(0.30),
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
    """Wilson score interval for binomial proportion. Handles k=0 correctly: 0/10 -> [0.00,0.28]."""
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
    Only valid for binary discordance (replications=1). For replications>1 use Wilcoxon/permutation.
    """
    n = bare_only + narr_only
    if n == 0:
        return None
    b = bare_only
    k = min(b, n - b)
    prob = 0.0
    for i in range(k + 1):
        prob += math.comb(n, i) / (2 ** n)
    p_two = min(1.0, 2 * prob)
    return p_two


def newcombe_paired_diff_interval(b: int, c: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Newcombe-style (method 10 adapted, conservative) interval for paired difference (b-c)/n.

    Uses Wilson intervals for b/n and c/n (square-and-add). Ignores negative correlation
    between b and c within pairs, so slightly conservative (too wide). Handles b=c=0:
    interval is [-Wilson(0/n).upper, +Wilson(0/n).upper] not [0,0].
    """
    if n == 0:
        return (0.0, 0.0)
    pb = b / n
    pc = c / n
    diff = pb - pc
    lb, ub = wilson_interval(b, n, z=z)
    lc, uc = wilson_interval(c, n, z=z)
    lower = diff - math.sqrt((pb - lb) ** 2 + (uc - pc) ** 2)
    upper = diff + math.sqrt((ub - pb) ** 2 + (pc - lc) ** 2)
    return (lower, upper)


def wilcoxon_signed_rank(d_list: List[float]) -> Tuple[float | None, float | None, int]:
    """Wilcoxon signed-rank test for paired differences d_i.

    Returns (W+, p_value, n_nonzero). W+ = sum of ranks where d_i>0.
    For n<=20 exact enumeration of sign assignments; for larger n normal approximation
    with tie correction. Returns (None,None,0) if all zeros.
    Valid for continuous d_i (replications>1) and binary (replications=1).
    """
    # Filter zeros
    filtered = [(abs(d), 1 if d > 0 else -1) for d in d_list if abs(d) > 1e-12]
    n = len(filtered)
    if n == 0:
        return None, None, 0
    # Rank absolute values, average ties
    # Sort by abs value
    sorted_abs = sorted(filtered, key=lambda x: x[0])
    # Assign ranks with tie averaging
    ranks = []
    i = 0
    while i < n:
        j = i
        while j < n and abs(sorted_abs[j][0] - sorted_abs[i][0]) < 1e-12:
            j += 1
        # tie from i to j-1, average rank = (i+1 + j)/2
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks.append((avg_rank, sorted_abs[k][1]))
        i = j
    # Sum positive ranks
    Wpos = sum(r for r, s in ranks if s > 0)
    # For exact test when n<=20, enumerate all 2^n sign assignments
    if n <= 20:
        # Observed Wpos, compute two-sided p: proportion of assignments with |W - expected| >= |obs - expected|
        expected = n * (n + 1) / 4.0
        obs_dev = abs(Wpos - expected)
        count_extreme = 0
        total = 1 << n  # 2^n
        # Enumerate via bitmask
        for mask in range(total):
            w = 0.0
            for idx in range(n):
                if (mask >> idx) & 1:
                    w += ranks[idx][0]
            if abs(w - expected) >= obs_dev - 1e-9:
                count_extreme += 1
        p = count_extreme / total
        return Wpos, p, n
    else:
        # Normal approximation with tie correction
        expected = n * (n + 1) / 4.0
        # Variance: n(n+1)(2n+1)/24 - sum(t^3 - t)/48 for ties
        # Compute tie correction
        # Group by abs value
        tie_groups = defaultdict(int)
        for abs_d, _ in filtered:
            # Use rounding for tie grouping
            tie_groups[round(abs_d, 12)] += 1
        var = n * (n + 1) * (2 * n + 1) / 24.0
        for t in tie_groups.values():
            if t > 1:
                var -= (t ** 3 - t) / 48.0
        if var <= 0:
            return Wpos, 1.0, n
        z = (Wpos - expected) / math.sqrt(var)
        # Two-sided p from normal
        # Phi via erf
        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        p = 2 * (1 - norm_cdf(abs(z)))
        return Wpos, min(1.0, p), n


def paired_permutation_p(d_list: List[float], n_perm: int = 10000, seed: int = 0) -> float | None:
    """Paired permutation test on mean d: swap framing labels within each instance (flip sign).

    Under H0, d_i sign is exchangeable. Compute observed mean, then permute signs.
    Returns two-sided p-value, or None if all zeros.
    """
    if not d_list:
        return None
    # Filter? Keep zeros, they don't affect mean sign flip? Include zeros, flipping doesn't change.
    # If all zeros, p undefined? Return None
    if all(abs(d) < 1e-12 for d in d_list):
        return None
    obs_mean = sum(d_list) / len(d_list)
    obs_abs = abs(obs_mean)
    rng = random.Random(seed)
    count_extreme = 0
    for _ in range(n_perm):
        # Flip each d_i sign with prob 0.5
        perm_mean = 0.0
        for d in d_list:
            perm_mean += d if rng.random() < 0.5 else -d
        perm_mean /= len(d_list)
        if abs(perm_mean) >= obs_abs - 1e-12:
            count_extreme += 1
    return count_extreme / n_perm


def format_p(p: float | None) -> str:
    if p is None:
        return "NA"
    if p < 1e-4:
        return "p<1e-4"
    return f"p={p:.4f}"


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
    # NOTE: solo and paired presentations of a given seed share same prior/likelihoods/observation,
    # so instance-level pairs may be correlated. We report both instance-level (n=presentations*seeds)
    # and seed-level aggregation (n=seeds) to avoid overstating effective sample size.
    instance_dict: Dict[Tuple, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    grouped_pooled: Dict[Tuple, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    per_seed: Dict[Tuple, Dict[str, Dict[int, List[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
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
    print("McNemar exact p only valid for replications=1 (binary discordance); for replications>1 use Wilcoxon/permutation on d_i")
    print("Newcombe-style (method 10 adapted, conservative) interval for paired diff: Wilson square-and-add on discordant props, ignores negative correlation")
    print("Seed-level aggregation: mean d per seed (avg over presentations) — avoids overstating n when solo/paired share same math problem")
    print("Seed variance = std of per-seed means; Repl variance = mean within-instance std across replications\n")

    overall_d: List[float] = []
    overall_bare_only = 0
    overall_narr_only = 0
    overall_pairs = 0
    overall_seed_d: List[float] = []

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
        # For seed-level aggregation
        seed_to_d: Dict[int, List[float]] = defaultdict(list)
        for inst_key in sorted(instance_dict):
            if inst_key[0] != scen or inst_key[1] != ev or inst_key[2] != prior:
                continue
            framings = instance_dict[inst_key]
            if "narrative" not in framings or "bare_table" not in framings:
                continue
            p_narr = sum(framings["narrative"]) / len(framings["narrative"]) if framings["narrative"] else 0.0
            p_bare = sum(framings["bare_table"]) / len(framings["bare_table"]) if framings["bare_table"] else 0.0
            d_i = p_narr - p_bare
            d_list.append(d_i)
            seed = inst_key[4]
            seed_to_d[seed].append(d_i)

            if abs(p_narr - 1.0) < 1e-9 and abs(p_bare - 1.0) < 1e-9:
                both_pass += 1
            elif abs(p_narr) < 1e-9 and abs(p_bare) < 1e-9:
                both_fail += 1
            elif d_i > 1e-9:
                narr_only += 1
            elif d_i < -1e-9:
                bare_only += 1

        # Seed-level d: mean over presentations per seed
        seed_d_list = [sum(v) / len(v) for v in seed_to_d.values()] if seed_to_d else []

        n_pairs = len(d_list)
        n_seeds = len(seed_d_list)
        if n_pairs:
            mean_d, std_d = mean_std(d_list)
            mean_d_seed, std_d_seed = mean_std(seed_d_list)
            newcombe_lo, newcombe_hi = newcombe_paired_diff_interval(narr_only, bare_only, n_pairs)
            lo_bare_only, hi_bare_only = wilson_interval(bare_only, n_pairs)
            lo_narr_only, hi_narr_only = wilson_interval(narr_only, n_pairs)

            # Tests: McNemar only valid when replications==1 (binary)
            if args.replications == 1:
                p_exact = exact_mcnemar_p(bare_only, narr_only)
                p_exact_str = format_p(p_exact)
                discordant = narr_only + bare_only
                if discordant > 0:
                    chi2 = (narr_only - bare_only) ** 2 / discordant
                    chi2_cc = (abs(narr_only - bare_only) - 1) ** 2 / discordant
                else:
                    chi2 = None
                    chi2_cc = None
                wilcox_p_str = "NA (binary, use McNemar)"
                perm_p_str = "NA (binary, use McNemar)"
            else:
                # For replications>1, d_i continuous, use Wilcoxon and permutation
                _, p_wilcox, _ = wilcoxon_signed_rank(d_list)
                p_perm = paired_permutation_p(d_list, n_perm=5000, seed=0)
                p_exact = None
                chi2 = None
                chi2_cc = None
                p_exact_str = "NA (replications>1, use Wilcoxon/perm)"
                wilcox_p_str = format_p(p_wilcox)
                perm_p_str = format_p(p_perm)

            # Seed-level tests (always Wilcoxon/permutation, since seed-level d is continuous even when repl=1? Actually seed-level mean over 2 presentations is continuous in {-1,-0.5,0,0.5,1})
            _, p_wilcox_seed, _ = wilcoxon_signed_rank(seed_d_list)
            p_perm_seed = paired_permutation_p(seed_d_list, n_perm=5000, seed=1)
            wilcox_seed_str = format_p(p_wilcox_seed)
            perm_seed_str = format_p(p_perm_seed)

        else:
            mean_d = std_d = mean_d_seed = std_d_seed = 0.0
            newcombe_lo = newcombe_hi = 0.0
            lo_bare_only = hi_bare_only = lo_narr_only = hi_narr_only = 0.0
            p_exact_str = "NA"
            chi2 = chi2_cc = None
            wilcox_p_str = perm_p_str = wilcox_seed_str = perm_seed_str = "NA"
            seed_d_list = []

        overall_d.extend(d_list)
        overall_bare_only += bare_only
        overall_narr_only += narr_only
        overall_pairs += n_pairs
        overall_seed_d.extend(seed_d_list)

        chi2_str = f"{chi2:.2f}" if chi2 is not None else "NA"
        chi2_cc_str = f"{chi2_cc:.2f}" if chi2_cc is not None else "NA"

        print(
            f"{scen},{ev},{prior}: n_pairs={n_pairs} instances (avg {args.replications} repl), n_seeds={n_seeds}\n"
            f"  pooled: narr {k_narr}/{n_narr} [{lo_narr:.2f},{hi_narr:.2f}] "
            f"(seed_std={seed_std_narr:.2f} n_seed={n_seed_narr} repl_std={repl_std_narr:.2f}) | "
            f"bare {k_bare}/{n_bare} [{lo_bare:.2f},{hi_bare:.2f}] "
            f"(seed_std={seed_std_bare:.2f} n_seed={n_seed_bare} repl_std={repl_std_bare:.2f})\n"
            f"  paired instance: mean d_i={mean_d:+.3f} std={std_d:.3f} "
            f"Newcombe-style [{newcombe_lo:+.2f},{newcombe_hi:+.2f}] (diff=narr_only-bare_only, conservative)\n"
            f"    discordant: both_pass={both_pass} both_fail={both_fail} "
            f"narr_only={narr_only} [{lo_narr_only:.2f},{hi_narr_only:.2f}] "
            f"bare_only={bare_only} (seduction) [{lo_bare_only:.2f},{hi_bare_only:.2f}] "
            f"McNemar χ²={chi2_str} (cc={chi2_cc_str}) exact {p_exact_str} | Wilcoxon {wilcox_p_str} perm {perm_p_str}\n"
            f"  paired seed: n={n_seeds} mean d_seed={mean_d_seed:+.3f} std={std_d_seed:.3f} "
            f"Wilcoxon {wilcox_seed_str} perm {perm_seed_str} (seed-level aggregation avoids overstating n)"
        )

    if overall_d:
        mean_d_all, _ = mean_std(overall_d)
        mean_d_seed_all, _ = mean_std(overall_seed_d)
        newcombe_lo_all, newcombe_hi_all = newcombe_paired_diff_interval(
            overall_narr_only, overall_bare_only, overall_pairs
        )
        lo_bare_all, hi_bare_all = wilson_interval(overall_bare_only, overall_pairs)
        # Overall tests: use seed-level for independence
        _, p_wilcox_all, _ = wilcoxon_signed_rank(overall_seed_d)
        p_perm_all = paired_permutation_p(overall_seed_d, n_perm=5000, seed=2)
        p_all = exact_mcnemar_p(overall_bare_only, overall_narr_only) if args.replications == 1 else None
        chi2_all = (overall_narr_only - overall_bare_only) ** 2 / (overall_narr_only + overall_bare_only) if (overall_narr_only + overall_bare_only) > 0 else None
        chi2_all_str = f"{chi2_all:.2f}" if chi2_all is not None else "NA"
        p_all_str = format_p(p_all) if args.replications == 1 else f"McNemar NA (repl>1) Wilcoxon {format_p(p_wilcox_all)} perm {format_p(p_perm_all)}"
        print(
            f"\nOverall (headline, pools evidence bands with different expected effects — per-group rows are primary):\n"
            f"  n_pairs={overall_pairs} instances, n_seeds={len(overall_seed_d)} seeds, "
            f"mean_d={mean_d_all:+.3f} mean_d_seed={mean_d_seed_all:+.3f} "
            f"Newcombe-style [{newcombe_lo_all:+.3f},{newcombe_hi_all:+.3f}] "
            f"bare_only (seduction)={overall_bare_only}/{overall_pairs} [{lo_bare_all:.2f},{hi_bare_all:.2f}] "
            f"narr_only={overall_narr_only} χ²={chi2_all_str} {p_all_str}"
        )

    if args.output:
        print(f"\nreport: {args.output}")


if __name__ == "__main__":
    main()
