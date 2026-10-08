#!/usr/bin/env python3
"""Turn a finished family run into invariance verdicts, without pretending to more.

Input is a suite manifest built by ``tools/suite_inventory.py --family`` (which carries
the planned pair identity) and a ``run_suite`` checkpoint (which carries what each
episode actually scored).  The report joins them per pair.

Three rules shape every verdict here:

* A delta is only reported for a pair whose identity both sides agree on.  If the
  episode recorded a different ``pair_id`` than the plan, the run is not part of this
  experiment, and it is labelled as such instead of being dropped quietly.
* An invariance is *observed*, never *established*: what is measured is that a scored
  outcome did not move across a declared transformation of the presentation.  Whether
  that means the model tracked an invariant is a claim about the model, and this tool
  has no access to it.
* Anything that could not be scored is ``not_measurable``, which is a distinct answer.
  Silence in the presence of a missing transport (a trajectory-gated evaluator on the
  shell transport, for instance) is data about the harness, not about the agent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 1

# Statuses that mean "an answer exists" rather than "the run broke before one did".
SCORED = {"scored"}


def _index_rows(checkpoint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in checkpoint.get("results") or []:
        case_id = str(row.get("case_id") or "")
        if case_id:
            rows[case_id] = row
    return rows


def _delta(member: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    """Score/answer movement between a member and the baseline of its own pair."""
    if baseline is None:
        return {"measurable": False, "reason": "no baseline row for this pair"}
    if member.get("status") not in SCORED or baseline.get("status") not in SCORED:
        blocked = [
            str(row.get("status"))
            for row in (member, baseline)
            if row.get("status") not in SCORED
        ]
        return {
            "measurable": False,
            "reason": "not_measurable: " + ", ".join(blocked),
            "failure_modes": sorted(
                {
                    str(row.get("failure_mode"))
                    for row in (member, baseline)
                    if row.get("failure_mode")
                }
            ),
        }
    member_score = member.get("score")
    baseline_score = baseline.get("score")
    if not isinstance(member_score, (int, float)) or not isinstance(baseline_score, (int, float)):
        return {"measurable": False, "reason": "not_measurable: a row carries no numeric score"}
    return {
        "measurable": True,
        "score_delta": round(float(member_score) - float(baseline_score), 6),
        "member_score": member_score,
        "baseline_score": baseline_score,
        "answer_delta": (
            None
            if member.get("verdict") is None or baseline.get("verdict") is None
            else bool(member.get("verdict") != baseline.get("verdict"))
        ),
    }


def _verdict(plan: dict[str, Any], delta: dict[str, Any]) -> str:
    """Classify one member against its own declaration.

    The vocabulary is deliberately two-sided: ``invariance_observed`` and
    ``no_sensitivity`` are both readings of "the number did not move", and which one
    is informative depends only on what the member declared it expected.
    """
    if not delta.get("measurable"):
        return "not_measurable"
    if plan.get("provenance_mismatch"):
        return "identity_mismatch"
    moved = abs(float(delta["score_delta"])) > 0.0
    expect = str(plan.get("expect") or "")
    if expect == "invariant":
        return "invariance_observed" if not moved else "sensitive"
    if expect == "sensitive":
        return "sensitivity_observed" if moved else "no_sensitivity"
    return "unspecified_expectation"


def build_report(
    manifest: dict[str, Any], checkpoint: dict[str, Any], *, spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    rows = _index_rows(checkpoint)
    plans: list[dict[str, Any]] = []
    for case in manifest.get("cases") or []:
        family = case.get("family")
        if not isinstance(family, dict):
            continue
        plans.append({**family, "case_id": case.get("case_id"), "environment": case.get("environment")})
    if not plans:
        raise ValueError(
            "this manifest carries no family cases; build it with "
            "tools/suite_inventory.py --family <dir>"
        )

    planned = {str(plan["case_id"]): plan for plan in plans}
    verdicts: list[dict[str, Any]] = []
    for plan in plans:
        case_id = str(plan["case_id"])
        if plan.get("role") == "baseline":
            verdicts.append(
                {
                    "case_id": case_id,
                    "role": "baseline",
                    "environment": plan.get("environment"),
                    "interventions": _interventions_of(manifest, case_id),
                    "pair_id": plan.get("pair_id"),
                    "verdict": "reference",
                }
            )
            continue
        member_row = rows.get(case_id) or {}
        baseline_id = plan.get("baseline_case_id")
        baseline_row = rows.get(str(baseline_id)) if baseline_id else None
        delta = _delta(member_row, baseline_row) if member_row else {
            "measurable": False,
            "reason": "not_measurable: the case was never run",
        }
        mismatch = [
            field
            for field, key in (("pair_id", "pair_id"), ("generation_id", "generation_id"))
            if member_row.get(key)
            and plan.get(field)
            and str(member_row[key]) != str(plan[field])
        ]
        entry = {
            "case_id": case_id,
            "role": "member",
            "environment": plan.get("environment"),
            "interventions": _interventions_of(manifest, case_id),
            "expect": plan.get("expect"),
            "equivalences": plan.get("equivalences") or [],
            "defect_classes": plan.get("defect_classes") or [],
            "twin_check": plan.get("twin_check"),
            "measurements": plan.get("measurements") or [],
            "hypotheses": plan.get("hypotheses") or [],
            "baseline_case_id": baseline_id,
            "pair_id_planned": plan.get("pair_id"),
            "pair_id_run": member_row.get("pair_id"),
            "pair_id_stable": bool(
                plan.get("pair_id")
                and member_row.get("pair_id")
                and str(plan["pair_id"]) == str(member_row["pair_id"])
            ),
            "provenance_mismatch": mismatch,
            "status": member_row.get("status", "not_run"),
            "movement": delta,
        }
        verdict = _verdict(entry, delta)
        # A declaration twin_check could not prove is not a failed invariance; it is an
        # invariance that was never falsifiable in the first place.
        if verdict in {"invariance_observed", "sensitivity_observed"} and plan.get("twin_check") != "pass":
            verdict = f"{verdict}_declaration_unproved"
        entry["verdict"] = verdict
        verdicts.append(entry)

    by_intervention: dict[str, list[dict[str, Any]]] = {}
    for entry in verdicts:
        if entry.get("role") != "member":
            continue
        for iid in entry.get("interventions") or ["(none)"]:
            by_intervention.setdefault(str(iid), []).append(entry)

    pooled: dict[str, Any] = {}
    for iid, entries in sorted(by_intervention.items()):
        measurable = [
            entry for entry in entries if entry["movement"].get("measurable")
        ]
        deltas = [float(entry["movement"]["score_delta"]) for entry in measurable]
        counts: dict[str, int] = {}
        for entry in entries:
            counts[str(entry["verdict"])] = counts.get(str(entry["verdict"]), 0) + 1
        pooled[iid] = {
            "members": len(entries),
            "measurable": len(measurable),
            "mean_score_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
            "directions": {
                "moved": sum(1 for value in deltas if abs(value) > 0.0),
                "did_not_move": sum(1 for value in deltas if abs(value) == 0.0),
            },
            "verdict_counts": counts,
            "seeds": sorted({int(entry["case_id"].rsplit("seed-", 1)[-1]) for entry in entries
                             if "seed-" in str(entry["case_id"])}),
        }

    counts_all: dict[str, int] = {}
    for entry in verdicts:
        counts_all[str(entry["verdict"])] = counts_all.get(str(entry["verdict"]), 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "rl_eval_generator_family_report",
        "manifest_case_count": len(manifest.get("cases") or []),
        "checkpoint_result_count": len(rows),
        "planned_pair_count": sum(1 for plan in plans if plan.get("role") != "baseline"),
        "verdict_counts": counts_all,
        "by_intervention": pooled,
        "entries": verdicts,
        "unrun_cases": sorted(set(planned) - set(rows)),
        "claim_ceiling": (spec or {}).get(
            "claim_ceiling",
            "behavioral_association_only - deltas between generated members measure "
            "sensitivity to a declared transformation, not what a model represented",
        ),
        "reading_rules": [
            "invariance_observed: the score did not move across a presentation change "
            "whose twins twin_check proved textually identical",
            "*_declaration_unproved: the direction of the result is reported, but the "
            "declaration behind it was not proved, so it is not evidence about the "
            "invariance the label claims",
            "identity_mismatch: the episode ran a different instance than the plan, so "
            "its score belongs to another experiment",
            "not_measurable: no scored verdict exists; this is a harness or transport "
            "answer and never a zero",
        ],
    }


def _interventions_of(manifest: dict[str, Any], case_id: str) -> list[str]:
    for case in manifest.get("cases") or []:
        if str(case.get("case_id")) == str(case_id):
            return [
                part.strip()
                for part in str(case.get("interventions") or "").split(",")
                if part.strip()
            ]
    return []


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True, help="suite manifest with family cases")
    parser.add_argument("--checkpoint", type=Path, required=True, help="run_suite checkpoint json")
    parser.add_argument("--spec", type=Path, default=None, help="the environment experiment spec, for its claim ceiling")
    parser.add_argument("--json", type=Path, default=None, help="write the full report here")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any planned pair came back not_measurable or identity_mismatch",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        checkpoint = json.loads(args.checkpoint.read_text(encoding="utf-8"))
        spec = load_yaml(args.spec) if args.spec else None
        report = build_report(manifest, checkpoint, spec=spec)
    except (OSError, ValueError) as exc:
        print(f"family report failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"family report: {report['planned_pair_count']} planned pairs, "
        + ", ".join(f"{key} {value}" for key, value in sorted(report["verdict_counts"].items()))
    )
    for iid, summary in report["by_intervention"].items():
        print(
            f"  {iid}: mean score delta {summary['mean_score_delta']} "
            f"over {summary['measurable']}/{summary['members']} measurable members "
            f"({summary['directions']['moved']} moved, "
            f"{summary['directions']['did_not_move']} did not)"
        )
    print(f"  claim ceiling: {str(report['claim_ceiling']).strip()}")
    if report["unrun_cases"]:
        print(f"  {len(report['unrun_cases'])} planned cases have no result row")
    if args.strict:
        blocked = [
            entry["case_id"]
            for entry in report["entries"]
            if entry.get("verdict") in {"not_measurable", "identity_mismatch"}
            and entry.get("role") == "member"
        ]
        if blocked:
            print(f"strict: {len(blocked)} pairs produced no usable verdict", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
