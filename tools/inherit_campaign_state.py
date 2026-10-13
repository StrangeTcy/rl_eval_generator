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

Gate rows are adopted across identities only on proof, never on policy: the tool shows,
with `git diff` over the verdict-relevant file set, that the code which produced them is
byte-identical to the code which will read them. That is what lets rows banked under the
old ``git rev-parse HEAD`` context survive the move to a content digest without
weakening the guard - see ``grading_code_identical()``. An unreachable revision is a
refusal that names the fetch to run, never a guess.

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
import re
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

try:  # noqa: E402  (same repo-root sys.path trick as above)
    from tools import gate_context
except ImportError:  # pragma: no cover - only on a checkout predating the content digest
    gate_context = None
# Explicitly not inherited; named so an operator can see the boundary was drawn.
# `state_contract_stop.json` counts consecutive legs that the carried state was refused at, *per code
# commit* - inheriting it from another campaign would make an inherited count escalate a fresh campaign's
# first refusal to an operator gate, which is exactly the trap that froze Mercury at 190 / 416.
NOT_INHERITED = (
    "suite_checkpoint.json",
    "campaign_intent.json",
    "wrapper_failed.json",
    "state_contract_stop.json",
)


REVISION_SHA = re.compile(r"^[0-9a-f]{40}$")


def grading_code_identical(
    source_context: str | None,
    *,
    root: Path | None = None,
) -> tuple[bool, str]:
    """Can rows banked under the old revision-pinned context be adopted here?

    Rows were keyed on ``git rev-parse HEAD`` until the context became the digest of the
    verdict-producing files, so every campaign that ran before that change holds rows
    under a 40-character revision that no future content digest can equal. Refusing all
    of them would silently void the inheritance step this tool implements; accepting
    them by fiat would launder the guard. So the answer is computed instead of asserted:
    the verdict-relevant files (``tools/gate_context.py``'s list) must be byte-identical
    between the revision the rows were produced at and the code that will read them. That
    is the same claim the old key was trying to make, stated about the files that matter.

    Fails closed. An unreachable revision -- a shallow checkout, a rewritten branch --
    returns a refusal that names the fetch to run, because guessing here means trusting a
    verdict produced by code nobody looked at.
    """
    if not source_context or not REVISION_SHA.match(str(source_context)):
        return False, "source context is not a revision, so there is nothing to compare"
    root = root or ROOT

    def _relative(path: Path) -> str:
        # The checkout the rows came from and the checkout being compared against can
        # be different trees (tests, audits), so resolve each path against whichever
        # root owns it rather than assuming one.
        for base in (root, ROOT):
            try:
                return str(path.relative_to(base))
            except ValueError:
                continue
        return str(path)

    paths = sorted(_relative(path) for path in gate_context.verdict_relevant_files())
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "diff", "--name-only", f"{source_context}", "HEAD", "--", *paths],
            cwd=root, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        return False, (
            f"cannot read {source_context} in this checkout"
            + (f" ({detail[-1]})" if detail else "")
            + f"; fetch it first: git fetch --no-tags --depth=1 origin {source_context}"
        )
    except OSError as exc:
        return False, f"git unavailable: {exc}"
    changed = [line for line in completed.stdout.splitlines() if line.strip()]
    if changed:
        listed = ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else "")
        return False, f"grading code differs in {len(changed)} file(s): {listed}"
    return True, f"grading code byte-identical to {source_context[:12]}"


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
    grading_diff_root: Path | None = None,
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
        carry = False
        if not rows:
            report["gate_rows_status"] = "source_has_no_rows"
        elif not context_sha:
            # Without a current context there is nothing to key the rows to, and the
            # campaign that would read them rejects them anyway. Say which side failed.
            report["gate_rows_status"] = "refused_gate_context_differs"
            report["gate_rows_refusal_note"] = "no current verdict context could be computed"
        elif source_context == context_sha:
            carry = True
        else:
            identical, note = grading_code_identical(source_context, root=grading_diff_root)
            if identical:
                # Rows banked under the old revision-pinned key, from grading code
                # provably identical to this checkout's. The proof is recorded beside
                # the rows, so the carry is auditable rather than taken on trust.
                report["gate_rows_rekeyed_from"] = source_context
                report["gate_rows_rekey_note"] = note
                carry = True
            else:
                # Refusing here is the point of the check: the verdict was produced by
                # different code, so re-gating is what an honest campaign does.
                report["gate_rows_status"] = "refused_gate_context_differs"
                report["gate_rows_refusal_note"] = note
        if carry:
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
            # recorded beside it. Gate rows get no such exception: a row from other
            # grading code is adopted only when grading_code_identical() proves the
            # verdict-relevant files are byte-identical, which is a check rather than
            # an operator's word.
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
    if args.context is not None:
        context = args.context
    elif args.head is not None:
        context = args.head
    elif gate_context is not None:
        context = gate_context.compute()
    else:
        # The launcher runs this tool against the campaign's pinned checkout, so an
        # old checkout can be missing tools/gate_context.py while its run_suite still
        # keys rows on `git rev-parse HEAD`. Keying on the revision there is not a
        # fallback to a weaker rule - it is the identity that reader will check.
        context = current_head()
        print(
            "no tools/gate_context.py in this checkout: keying gate rows on the "
            "revision, which is what this pinned run_suite compares against"
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
