#!/usr/bin/env python3
"""T1 ``same_fact_presentation`` behavior probe (matched-fact presentation).

The runnable harness for the ``arena/matched_facts.py`` contract. For each
frozen matched-fact instance it presents the IDENTICAL evidence set under two
presentations (canonical/bullet vs reversed/numbered), runs one answer source
against both arms, and records the target's behavior as SEPARATE endpoints
(diagnostic choices, elicited belief, terminal outcome; inquiry regret and
recovery are not_measurable in a single turn). It then reports *presentation
susceptibility* - the structured, per-endpoint divergence across the matched
arms - and never collapses it into a single score.

Answer sources
--------------
Offline baselines (no model, no network), each a pure function of the public
presentation except the calibration upper bound:

  calibrated      the exact order-invariant oracle (NOT public-only; a sanity
                  upper bound that must show ZERO presentation susceptibility)
  prior_anchored  always answers the prior, ignores evidence and order (a flat
                  null control: zero susceptibility, incorrect belief)
  primacy_biased  recomputes from the FIRST-presented fact only (positive
                  control: order-sensitive, so susceptibility is detected)
  recency_biased  recomputes from the LAST-presented fact only (positive control)

External answer source (any callable), as in tools/epistemic_probe.py:

  --module my_answers.py:answer_fn      answer_fn(presentation: dict) -> dict

Model adapter (real target; makes provider calls, so it is only used where an
API key is authorized - e.g. the campaign workflows):

  --provider mercury --model mercury-2.5 [--reasoning-effort high]
  --provider atria   --model Atria-Dawn-Preview

Usage (offline)::

    python tools/matched_fact_probe.py --baseline primacy_biased --seeds 8
    python tools/matched_fact_probe.py --baseline calibrated --seeds 8 --out runs/t1/calibrated.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.matched_facts import (  # noqa: E402
    INQUIRY_MENU,
    NOT_MEASURABLE,
    AnswerSource,
    MatchedFactTask,
    assert_reporting_boundary,
    build_trial,
    compute_susceptibility,
    public_presentation,
    sample_bayesian_matched_facts,
    susceptibility_report,
)
from shared.epistemic_semantics import bayes  # noqa: E402

# A source builder receives the task (so the calibration baseline can capture
# the oracle) and returns an AnswerSource. Pure baselines ignore the task.
SourceBuilder = Callable[[MatchedFactTask], AnswerSource]


# ---------------------------------------------------------------------------
# Offline baselines.
# ---------------------------------------------------------------------------


def _bayes_answer(posterior: Fraction) -> Dict[str, object]:
    if posterior > Fraction(1, 2):
        most = "world1"
    elif posterior < Fraction(1, 2):
        most = "world2"
    else:
        most = "neither"
    return {"_most": most}


def make_calibrated_source(task: MatchedFactTask) -> AnswerSource:
    """Calibration upper bound: the exact oracle, identical for both arms.

    NOT public-only (it reads the task oracle). A correct, order-invariant
    target must show zero presentation susceptibility; this baseline proves the
    metric does not fire on order-invariant behavior.
    """

    def source(presentation: Mapping[str, object]) -> Dict[str, object]:
        return {
            "elicited_belief": task.oracle_posterior_world1,
            "terminal_answer": task.oracle_answer(),
            "diagnostic_choices": ["conclude_no_further_inquiry"],
            "justification": "calibrated oracle (not public-only)",
        }

    return source


def _evidence_posterior(item: Mapping[str, object]) -> Fraction:
    l1 = Fraction(str(item["likelihood_world1"]))
    l2 = Fraction(str(item["likelihood_world2"]))
    return bayes.posterior_world1(Fraction(1, 2), l1, l2)


def _single_evidence_source(position: str) -> AnswerSource:
    """Answer from ONE evidence item (first or last in the presented order).

    A pure function of the public presentation: it reads the ordered public
    evidence items, never the oracle and never the rendered text. Because the
    chosen item differs between the matched arms, this source is order-sensitive
    and the probe must flag presentation susceptibility.
    """

    def source(presentation: Mapping[str, object]) -> Dict[str, object]:
        items = presentation["evidence_items"]
        assert isinstance(items, list) and items
        item = items[0] if position == "first" else items[-1]
        posterior = _evidence_posterior(item)  # type: ignore[arg-type]
        most = _bayes_answer(posterior)["_most"]
        _ratio, verdict = bayes.likelihood_ratio_band(
            Fraction(str(item["likelihood_world1"])),  # type: ignore[arg-type]
            Fraction(str(item["likelihood_world2"])),  # type: ignore[arg-type]
        )
        choice = "recheck_first_evidence" if position == "first" else "recheck_last_evidence"
        return {
            "elicited_belief": posterior,
            "terminal_answer": f"{most}:{verdict}",
            "diagnostic_choices": [choice],
            "justification": f"{position}-presented evidence only",
        }

    return source


primacy_biased = _single_evidence_source("first")
recency_biased = _single_evidence_source("last")


def prior_anchored(presentation: Mapping[str, object]) -> Dict[str, object]:
    """Flat null control: always the prior, ignores evidence and order."""
    return {
        "elicited_belief": Fraction(1, 2),
        "terminal_answer": f"neither:{bayes.VERDICT_INDISTINGUISHABLE}",
        "diagnostic_choices": ["conclude_no_further_inquiry"],
        "justification": "prior only",
    }


BASELINES: Dict[str, SourceBuilder] = {
    "calibrated": make_calibrated_source,
    "prior_anchored": lambda task: prior_anchored,
    "primacy_biased": lambda task: primacy_biased,
    "recency_biased": lambda task: recency_biased,
}


# ---------------------------------------------------------------------------
# Model adapter (real provider calls; authorized contexts only).
# ---------------------------------------------------------------------------

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_ANSWER_SCHEMA = (
    "Answer with ONLY a JSON object of this exact shape:\n"
    '{"posterior_world1": "<fraction or decimal, e.g. 3/5 or 0.6>",\n'
    ' "verdict": "indistinguishable|weakly_distinguishable|distinguishable",\n'
    ' "most_supported": "world1|world2|neither",\n'
    ' "diagnostic_choices": ["<zero or more of: '
    + ", ".join(INQUIRY_MENU)
    + '>"],\n'
    ' "justification": "<one short sentence>"}\n'
)


def _parse_belief(value: object) -> Optional[Fraction]:
    if value is None:
        return None
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None


def _extract_json(content: str) -> Optional[dict]:
    match = _JSON_BLOCK.search(content or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def make_model_source(
    client,
    model: str,
    *,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    reasoning_effort: Optional[str] = None,
    top_p: Optional[float] = None,
) -> AnswerSource:
    """Wrap a ProviderClient as an AnswerSource for one target model.

    The prompt carries only public content (task question + rendered evidence +
    the inquiry menu + the answer schema). The oracle and the fact-set id are
    never sent. A response that cannot be parsed yields null endpoints (scored
    not_measurable/incorrect) rather than raising, so one bad completion cannot
    abort a campaign leg.
    """
    request_extra: Dict[str, object] = {}
    if reasoning_effort:
        request_extra["reasoning_effort"] = reasoning_effort

    def source(presentation: Mapping[str, object]) -> Dict[str, object]:
        prompt = (
            f"{presentation['task_question']}\n\n"
            f"Evidence (presentation variant {presentation['variant']}):\n"
            f"{presentation['evidence_presentation']}\n\n"
            f"{_ANSWER_SCHEMA}"
        )
        completion = client.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            request_extra=request_extra or None,
        )
        data = _extract_json(completion.content)
        if data is None:
            return {
                "elicited_belief": None,
                "terminal_answer": None,
                "diagnostic_choices": [],
                "justification": "unparseable_response",
            }
        most = str(data.get("most_supported", "")).strip()
        verdict = str(data.get("verdict", "")).strip()
        terminal = f"{most}:{verdict}" if most and verdict else None
        return {
            "elicited_belief": _parse_belief(data.get("posterior_world1")),
            "terminal_answer": terminal,
            "diagnostic_choices": data.get("diagnostic_choices") or [],
            "justification": str(data.get("justification", ""))[:500],
        }

    return source


def load_module_source(spec: str) -> AnswerSource:
    """Load an external ``path.py:callable`` answer source (epistemic_probe style)."""
    import importlib.util

    if ":" not in spec:
        raise ValueError("--module must look like path/to/module.py:callable")
    path_text, attr = spec.split(":", 1)
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    loaded = importlib.util.spec_from_file_location(f"t1_source_{attr}", path)
    if loaded is None or loaded.loader is None:
        raise ValueError(f"cannot import answer source from {path}")
    module = importlib.util.module_from_spec(loaded)
    sys.modules[loaded.name] = module
    loaded.loader.exec_module(module)
    fn = getattr(module, attr)
    if not callable(fn):
        raise ValueError(f"{attr!r} in {path} is not callable")
    return fn  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Probe run + reporting (endpoints kept separate; never one collapsed score).
# ---------------------------------------------------------------------------


def run_probe(
    source_builder: SourceBuilder,
    *,
    seeds: Sequence[int],
    n_facts: int = 4,
    prior_world1: Fraction = Fraction(1, 2),
) -> Dict[str, object]:
    """Run the matched-fact probe over ``seeds`` and build a boundary-safe report."""
    trials: List[Dict[str, object]] = []
    order_invariant_trials = 0
    belief_deltas: List[str] = []
    diverged_histogram: Dict[str, int] = {}

    for seed in seeds:
        task = sample_bayesian_matched_facts(seed, n_facts=n_facts, prior_world1=prior_world1)
        source = source_builder(task)
        trial = build_trial(task, source)
        susc = compute_susceptibility(trial)
        report = susceptibility_report(susc)
        # Per-trial record keeps the endpoints separate.
        trials.append(
            {
                "seed": seed,
                "semantic_fact_id": task.semantic_fact_id,
                "fact_count": task.fact_count if hasattr(task, "fact_count") else len(task.facts),
                "oracle_answer": task.oracle_answer(),
                "oracle_posterior_world1": str(task.oracle_posterior_world1),
                "arms": {
                    "a": _arm_record(trial.arm_a),
                    "b": _arm_record(trial.arm_b),
                },
                **report,
            }
        )
        if not susc.diverged_endpoints:
            order_invariant_trials += 1
        if susc.belief_delta not in (Fraction(0), 0) and susc.belief_delta != NOT_MEASURABLE:
            belief_deltas.append(str(susc.belief_delta))
        for endpoint in susc.diverged_endpoints:
            diverged_histogram[endpoint] = diverged_histogram.get(endpoint, 0) + 1

    aggregate = {
        "trial_count": len(trials),
        # Reported separately, never collapsed into one susceptibility score:
        "order_invariant_trials": order_invariant_trials,
        "order_sensitive_trials": len(trials) - order_invariant_trials,
        "diverged_endpoint_histogram": diverged_histogram,
        "belief_delta_values": belief_deltas,
    }
    full_report = {
        "probe": "t1_same_fact_presentation",
        "operator": "same_fact_presentation",
        "n_facts": n_facts,
        "prior_world1": str(prior_world1),
        "aggregate": aggregate,
        "trials": trials,
        "interpretation_boundary": (
            "Divergence across matched arms is presentation susceptibility only. "
            "It is not evidence of attention manipulation, an internal update-rule "
            "change, or harm; endpoints are reported separately and never collapsed."
        ),
    }
    assert_reporting_boundary(full_report)
    return full_report


def _arm_record(arm) -> Dict[str, object]:
    return {
        "variant": arm.variant,
        "diagnostic_choices": list(arm.diagnostic_choices),
        "elicited_belief": str(arm.elicited_belief) if arm.elicited_belief is not None else None,
        "belief_correct": arm.belief_correct,
        "terminal_answer": arm.terminal_answer,
        "terminal_correct": arm.terminal_correct,
        "inquiry_regret": arm.inquiry_regret,
        "recovery": arm.recovery,
        "justification": arm.justification,
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _seed_list(args: argparse.Namespace) -> List[int]:
    if args.seed_list:
        return [int(s) for s in args.seed_list.split(",") if s.strip() != ""]
    return list(range(args.seeds))


def _build_source_builder(args: argparse.Namespace) -> SourceBuilder:
    chosen = [bool(args.baseline), bool(args.module), bool(args.provider)]
    if sum(chosen) != 1:
        raise SystemExit("choose exactly one of --baseline, --module, --provider")
    if args.baseline:
        if args.baseline not in BASELINES:
            raise SystemExit(f"unknown baseline {args.baseline!r}; options: {sorted(BASELINES)}")
        return BASELINES[args.baseline]
    if args.module:
        fn = load_module_source(args.module)
        return lambda task: fn
    # Provider adapter.
    from arena.providers import ProviderClient
    from arena.secrets import resolve_provider

    creds = resolve_provider(args.provider, api_key_env=args.api_key_env)
    if not creds.api_key:
        raise SystemExit(
            f"no API key resolved for provider {args.provider!r} "
            f"(expected env {args.api_key_env or creds.name.upper() + '_API_KEY'})"
        )
    client = ProviderClient(
        args.provider,
        creds.api_key,
        api_base=creds.api_base,
        min_interval_seconds=args.min_interval_seconds,
    )
    return lambda task: make_model_source(
        client,
        args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        reasoning_effort=args.reasoning_effort,
        top_p=args.top_p,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_argument_group("answer source (choose exactly one)")
    group.add_argument("--baseline", choices=sorted(BASELINES))
    group.add_argument("--module", help="path/to/module.py:callable answer source")
    group.add_argument("--provider", help="registered provider name (e.g. mercury, atria)")
    parser.add_argument("--model", help="model id for --provider")
    parser.add_argument("--api-key-env", help="override the provider key env var")
    parser.add_argument("--reasoning-effort", help="Mercury reasoning_effort: low|medium|high")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--min-interval-seconds", type=float, default=0.0)
    parser.add_argument("--seeds", type=int, default=8, help="run seeds 0..N-1")
    parser.add_argument("--seed-list", help="explicit comma-separated seeds")
    parser.add_argument("--n-facts", type=int, default=4)
    parser.add_argument("--prior-world1", default="1/2")
    parser.add_argument("--out", help="write the JSON report here (and to stdout)")
    args = parser.parse_args(argv)

    if args.provider and not args.model:
        raise SystemExit("--provider requires --model")

    builder = _build_source_builder(args)
    report = run_probe(
        builder,
        seeds=_seed_list(args),
        n_facts=args.n_facts,
        prior_world1=Fraction(args.prior_world1),
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
