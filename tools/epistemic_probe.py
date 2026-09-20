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
-----
    python tools/epistemic_probe.py --baseline seductive --seeds 5
    python tools/epistemic_probe.py --baseline calibrated --seeds 3 --output report.jsonl
    python tools/epistemic_probe.py --module my_answers.py:answer_fn --seeds 5
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List

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
    # "They announced it directly, so they must be the genuine type."
    if public["observation"] == "denial":
        return make_answer(public, 0.8, "distinguishable", "world1",
                           "a direct denial is what a genuine player says")
    return make_answer(public, 0.3, "distinguishable", "world2",
                       "evasiveness reeks of strategy")


def baseline_overcautious(public: dict) -> dict:
    # "If it is this clean, it must be deliberate."
    if public["observation"] == "denial":
        return make_answer(public, 0.2, "distinguishable", "world2",
                           "a perfect denial is the strategic player's tell")
    return make_answer(public, 0.7, "distinguishable", "world1",
                       "vagueness is what a flustered genuine player does")


def baseline_narrative_match(public: dict) -> dict:
    # Match the transcript to the world whose narrative fits the utterance.
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", choices=sorted(BASELINES),
                        help="built-in fixed answer source")
    parser.add_argument("--module", default="",
                        help="external answer source: path.py:function_name(public)->dict")
    parser.add_argument("--seeds", type=int, default=5,
                        help="seeds per axis combination (0..seeds-1)")
    parser.add_argument("--output", default="",
                        help="optional JSONL report path")
    args = parser.parse_args()

    if bool(args.baseline) == bool(args.module):
        parser.error("exactly one of --baseline or --module is required")

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

    print(f"\nepistemic_games probe: answer_source={name} instances={len(rows)}\n")
    header = f"{'failure_mode':<28} {'ambiguous':>10} {'weak':>8} {'strong':>8} {'total':>8}"
    print(header)
    print("-" * len(header))
    for mode in sorted(modes, key=lambda m: (-sum(modes[m].values()), m)):
        counts = modes[mode]
        print(f"{mode:<28} {counts['ambiguous']:>10} {counts['weak']:>8} {counts['strong']:>8} "
              f"{sum(counts.values()):>8}")
    passed = sum(1 for r in rows if r["failure_mode"] == "pass")
    print(f"\npass: {passed}/{len(rows)}")

    # Bare-table vs narrative control: group by (scenario, evidence, prior) and
    # measure delta in failure_mode frequencies between framings.
    from collections import Counter, defaultdict

    grouped: Dict[tuple, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for r in rows:
        key = (r["scenario"], r["evidence"], r["prior"])
        grouped[key][r["framing"]][r["failure_mode"]] += 1

    print("\n--- Narrative vs Bare-Table delta (matched by scenario,evidence,prior) ---")
    for key in sorted(grouped):
        scen, ev, prior = key
        narr = grouped[key].get("narrative", Counter())
        bare = grouped[key].get("bare_table", Counter())
        if narr != bare:
            total_narr = sum(narr.values())
            total_bare = sum(bare.values())
            pass_narr = narr.get("pass", 0)
            pass_bare = bare.get("pass", 0)
            print(
                f"{scen},{ev},{prior}: pass narrative {pass_narr}/{total_narr} vs bare {pass_bare}/{total_bare} "
                f"delta={pass_bare - pass_narr:+d} | narr {dict(narr)} vs bare {dict(bare)}"
            )

    if args.output:
        print(f"\nreport: {args.output}")


if __name__ == "__main__":
    main()
