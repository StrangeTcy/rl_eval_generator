#!/usr/bin/env python3
"""Seed a new campaign's checkpoint with the exact-instance gate rows of an earlier one.

Why this is legitimate at all: switching matrix mode changes case ids, so a
campaign moving from strength-1 to strength-2 cannot *resume* the old run. But the
gate rows are not plan-bound - ``run_suite`` keys each row on the case dict's own
content hash and accepts it only under the same gate context, and the gate context
is the digest of the verdict-relevant file set (``tools/gate_context.py``), not the
repository revision. So a verified row carries across a plan change when, and only
when, both campaigns run grading code that is byte-identical. When that digest
differs -- a generator, an environment template, a requirement changed -- refusing
the carry is the correct outcome, not an inconvenience: the row's verdict is a claim
about *this* code grading *this* instance. This tool therefore never rewrites a
``gate_context_sha`` to make rows acceptable.

A commit-only difference no longer blocks the carry, and that is the point: the
previous revision-pinned rule discarded every banked row on a documentation commit,
which turned a multi-leg gate phase into a loop that could never finish.

What is never inherited: the episode ledger (``suite_checkpoint.json``), the
campaign intent, terminal markers, and anything else campaign-scoped - budget
accounting, per-case dispositions and the research contract belong to one campaign.
T1's report is inherited only when the source campaign ran this same commit, because
that probe is a measurement of model-plus-code, not of the matrix.

Usage:
  python tools/inherit_campaign_state.py \
      --from /tmp/restored-covering-state --to runs/mercury_pairwise_campaign \
      --profile experiments/mercury_pairwise_campaign.yaml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GATE_FILE = "instance_oracles_partial.json"
T1_REPORT = "t1_same_fact_presentation.json"
T1_PLAN = "t1_plan.json"
CAMPAIGN_REF = "campaign_ref.txt"

from tools import gate_context  # noqa: E402  (same repo-root sys.path trick as above)
# Explicitly not inherited; named so an operator can see the boundary was drawn.
NOT_INHERITED = ("suite_checkpoint.json", "campaign_intent.json", "wrapper_failed.json")


def case_sha256(case: dict[str, Any]) -> str:
    """The same digest ``run_suite`` computes for a gated case."""
    return hashlib.sha256(json.dumps(case, sort_keys=True).encode("utf-8")).hexdigest()


def current_head(root: Path = ROOT) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def plan_cases(*, profile_path: Path | None, manifest_path: Path | None) -> dict[str, str]:
    """{case_id: case_sha256} for the plan the new campaign is about to bill."""
    if manifest_path is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif profile_path is not None:
        from tools.atria_campaign import (
            matrix_interventions_of,
            matrix_mode_of,
        )
        from tools.suite_inventory import build_manifest

        profile = yaml_profile(profile_path)
        manifest = build_manifest(
            root=ROOT,
            matrix=matrix_mode_of(profile),
            seeds=[0],
            expand_interventions=matrix_interventions_of(profile),
        )
    else:
        raise ValueError("either --profile or --manifest is required")
    return {
        str(case.get("case_id")): case_sha256(case)
        for case in manifest.get("cases") or []
        if case.get("case_id")
    }


def yaml_profile(path: Path) -> dict[str, Any]:
    import yaml  # local: only needed on the profile path

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def inherit_state(
    source: Path,
    target: Path,
    *,
    plan: dict[str, str],
    context_sha: str | None,
    head_sha: str | None = None,
    allow_cross_revision_t1: bool = False,
) -> dict[str, Any]:
    """Copy what the new campaign can lawfully reuse; report every judgement.

    ``context_sha`` is the identity rows must be keyed on -- the verdict-context
    digest this campaign will compute, i.e. what ``run_suite`` compares against.
    ``head_sha`` is recorded for provenance only; defaulting it to the digest keeps
    callers that think in revisions honest by accident rather than by luck.
    """
    target.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "source": str(source),
        "target": str(target),
        "context_sha": context_sha,
        "head_sha": head_sha if head_sha is not None else current_head(),
        "gate_rows_total": 0,
        "gate_rows_inherited": 0,
        "gate_rows_dropped_not_in_plan": 0,
        "gate_rows_dropped_hash_mismatch": 0,
        "gate_rows_dropped_not_passed": 0,
        "gate_rows_status": "no_source_file",
        "t1_inherited": False,
        "t1_reason": "no_source_report",
        "not_inherited_by_design": list(NOT_INHERITED),
    }

    source_gate = source / GATE_FILE
    target_gate = target / GATE_FILE
    if source_gate.is_file():
        try:
            payload = json.loads(source_gate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), dict) else {}
        source_context = payload.get("gate_context_sha")
        report["gate_rows_total"] = len(rows)
        report["gate_rows_source_context_sha"] = source_context
        if not rows:
            report["gate_rows_status"] = "source_has_no_rows"
        elif not context_sha or source_context != context_sha:
            # Refusing here is the point of the check: the verdict was produced by
            # different code, so re-gating is what an honest campaign does.
            report["gate_rows_status"] = "refused_gate_context_differs"
        else:
            kept: dict[str, Any] = {}
            if target_gate.is_file():
                try:
                    existing = json.loads(target_gate.read_text(encoding="utf-8"))
                    if isinstance(existing.get("rows"), dict) and existing.get("gate_context_sha") == context_sha:
                        kept = dict(existing["rows"])
                except (OSError, json.JSONDecodeError):
                    kept = {}
            inherited = 0
            for case_id, entry in rows.items():
                if case_id not in plan:
                    report["gate_rows_dropped_not_in_plan"] += 1
                    continue
                if not isinstance(entry, dict) or entry.get("case_sha256") != plan[case_id]:
                    report["gate_rows_dropped_hash_mismatch"] += 1
                    continue
                if not isinstance(entry.get("row"), dict) or entry["row"].get("status") != "passed":
                    # A row the source campaign never validated is not a row to
                    # carry; counting it as a hash mismatch would blame the plan.
                    report["gate_rows_dropped_not_passed"] += 1
                    continue
                if case_id in kept:
                    continue  # a row this campaign already banked wins
                kept[case_id] = entry
                inherited += 1
            report["gate_rows_inherited"] = inherited
            report["gate_rows_status"] = "inherited" if inherited else "nothing_reusable"
            if inherited:
                merged = {"gate_context_sha": context_sha, "rows": kept}
                tmp = target_gate.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                tmp.replace(target_gate)

    source_ref = source / CAMPAIGN_REF
    source_t1 = source / T1_REPORT
    if (target / T1_REPORT).is_file():
        report["t1_reason"] = "target_already_has_report"
    elif not source_t1.is_file():
        report["t1_reason"] = "no_source_report"
    else:
        recorded = source_ref.read_text(encoding="utf-8").strip() if source_ref.is_file() else ""
        same_revision = bool(head_sha) and recorded == head_sha
        if same_revision or allow_cross_revision_t1:
            # Crossing revisions for T1 is an operator judgement, not a default: the
            # probe measures model-plus-code behaviour, so a report from another
            # revision is inherited only when asked for, and its source ref is
            # recorded beside it. Gate rows get no such exception - accepting a row
            # produced by different grading code would launder the guard.
            shutil.copyfile(source_t1, target / T1_REPORT)
            if (source / T1_PLAN).is_file():
                shutil.copyfile(source / T1_PLAN, target / T1_PLAN)
            report["t1_inherited"] = True
            report["t1_reason"] = (
                "same_revision" if same_revision
                else f"cross_revision_copy_from_{recorded or 'unknown_ref'}"
            )
            report["t1_source_ref"] = recorded
        else:
            report["t1_reason"] = f"source_revision_{recorded or 'unknown'}_differs_from_head"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", required=True, type=Path, help="restored state of the earlier campaign")
    parser.add_argument("--to", dest="target", required=True, type=Path, help="this campaign's state directory")
    parser.add_argument("--profile", type=Path, default=None, help="profile whose matrix defines the new plan")
    parser.add_argument("--manifest", type=Path, default=None, help="explicit manifest json (overrides --profile)")
    parser.add_argument("--head", default=None, help="override the current revision (tests/audits only)")
    parser.add_argument("--context", default=None,
                        help="override the verdict-context digest rows must match "
                             "(defaults to tools/gate_context.compute())")
    parser.add_argument(
        "--allow-cross-revision-t1", action="store_true",
        help="copy T1's report even if the source campaign ran a different revision (recorded in the report)",
    )
    args = parser.parse_args()
    if not args.source.is_dir():
        print(f"nothing to inherit from {args.source}; starting clean")
        return 0
    # Rows are matched on the verdict context; the revision is recorded beside it.
    # --head stays a revision override for audits, so an operator who wants the old
    # revision-pinned behaviour can still ask for it explicitly.
    context = args.context if args.context is not None else (
        args.head if args.head is not None else gate_context.compute()
    )
    head = args.head if args.head is not None else current_head()
    plan = plan_cases(profile_path=args.profile, manifest_path=args.manifest)
    report = inherit_state(
        args.source, args.target, plan=plan, context_sha=context, head_sha=head,
        allow_cross_revision_t1=bool(args.allow_cross_revision_t1),
    )
    out = args.target / "inheritance_report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"inherited gate rows: {report['gate_rows_inherited']}/{report['gate_rows_total']} "
        f"({report['gate_rows_status']}); dropped not-in-plan "
        f"{report['gate_rows_dropped_not_in_plan']}, hash-mismatch "
        f"{report['gate_rows_dropped_hash_mismatch']}; T1: "
        f"{'inherited' if report['t1_inherited'] else report['t1_reason']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
