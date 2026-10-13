#!/usr/bin/env python3
"""Verify every intervention twin a campaign manifest wants to bill, provider-free.

A campaign case that carries an intervention asserts a causal claim: ``expect:
invariant`` means "the model's behaviour should not move under this overlay".
That claim is only falsifiable if the overlay actually changed the instance, and
``tools/family.py`` is what proves it - it generates base and twin, then compares
the trees (``twin_check``) before any model is contacted.  Billing an intervention
case whose twin was never checked is precisely how "the agent was invariant"
becomes "the intervention did nothing", which is why ``envs/interventions.yaml``
insists an unimplemented id is a generation error and never a silent no-op.

Cases are grouped by (environment, difficulty vector, seed) so one ``family.py``
call verifies every twin sharing that base, and results are keyed by the exact
case ids the campaign will bill.

Modes:
  strict              a twin that does not verify fails the run before any provider call
  advisory            record the verdict, keep going (the campaign labels the rows)
  bill_verified_only  record the verdict and hand the caller the case ids whose
                      twin verified; the campaign drops the rest before billing
  off                 do not look

Usage:
  python tools/twin_preflight.py --manifest runs/x/pilot_manifest.json --out runs/x/twin_preflight.json
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAMILY_TOOL = ROOT / "tools" / "family.py"
MODES = ("strict", "advisory", "bill_verified_only", "off")


def intervention_groups(manifest: dict[str, Any]) -> dict[tuple[str, str, int], dict[str, list[str]]]:
    """{(environment, difficulty, seed): {intervention_id: [case_id, ...]}} for billed twins."""
    groups: dict[tuple[str, str, int], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for case in manifest.get("cases") or []:
        ids = case.get("interventions") or []
        if isinstance(ids, str):
            ids = [part for part in ids.split(",") if part]
        if not ids:
            continue
        key = (str(case["environment"]), str(case.get("difficulty") or ""), int(case.get("seed", 0)))
        for iid in ids:
            groups[key][str(iid)].append(str(case.get("case_id")))
    return dict(groups)


def _read_family_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest_twins(
    manifest: dict[str, Any],
    *,
    root: Path = ROOT,
    out_path: Path | None = None,
    mode: str = "advisory",
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Run ``tools/family.py`` for every (env, vector, seed) carrying interventions.

    Returns a report with one entry per group and one per billed case id, so a
    campaign record can say *which* twins verified rather than that a flag was on.
    """
    if mode not in MODES:
        raise ValueError(f"twin verification mode must be one of {MODES}")
    groups = intervention_groups(manifest)
    report: dict[str, Any] = {
        "policy": mode,
        "group_count": len(groups),
        "case_count": sum(len(ids) for group in groups.values() for ids in group.values()),
        "groups": [],
        "cases": {},
    }
    if mode == "off" or not groups:
        report["status"] = "skipped" if mode == "off" else "not_applicable"
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report

    tool = root / "tools" / "family.py"
    with tempfile.TemporaryDirectory(prefix="twin_preflight_") as tmp:
        workdir = Path(tmp)
        for (environment, difficulty, seed), by_intervention in sorted(groups.items()):
            ids = sorted(by_intervention)
            manifest_path = workdir / f"{environment}-{seed}-family.json"
            command = [
                sys.executable,
                str(tool),
                "--env", environment,
                "--seeds", str(seed),
                "--interventions", ",".join(ids),
                "--out", str(workdir / f"{environment}-{seed}"),
                "--json", str(manifest_path),
            ]
            if difficulty:
                command += ["--difficulty", difficulty]
            completed = subprocess.run(  # noqa: S603 - fixed tool, no shell
                command, cwd=str(root), capture_output=True, text=True, timeout=timeout_seconds
            )
            verdicts: dict[str, str] = {}
            family_verification: Any = None
            if manifest_path.exists():
                family_report = _read_family_json(manifest_path)
                family_verification = family_report.get("verification")
                for member in family_report.get("members") or []:
                    if member.get("role") == "baseline":
                        continue
                    member_ids = member.get("interventions") or []
                    if isinstance(member_ids, str):
                        member_ids = [part for part in member_ids.split(",") if part]
                    verdict = str(member.get("twin_check") or "unverified")
                    for iid in member_ids:
                        for case_id in by_intervention.get(str(iid), []):
                            verdicts[case_id] = verdict
            group_record = {
                "environment": environment,
                "difficulty": difficulty,
                "seed": seed,
                "interventions": ids,
                "family_exit_code": completed.returncode,
                "family_verification": family_verification,
                "verified": sum(1 for v in verdicts.values() if v == "pass"),
                "unverified": sum(1 for v in verdicts.values() if v != "pass"),
            }
            report["groups"].append(group_record)
            for case_id, verdict in verdicts.items():
                report["cases"][case_id] = {
                    "twin_check": verdict,
                    "family_exit_code": completed.returncode,
                }
            for case_id in itertools.chain.from_iterable(by_intervention.values()):
                report["cases"].setdefault(
                    case_id,
                    {
                        "twin_check": "error",
                        "family_exit_code": completed.returncode,
                        "detail": (completed.stderr or completed.stdout or "")[-400:],
                    },
                )
    unverified = sorted(cid for cid, rec in report["cases"].items() if rec["twin_check"] != "pass")
    report["unverified_case_count"] = len(unverified)
    report["unverified_case_ids"] = unverified
    report["status"] = "passed" if not unverified else "unverified"
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report["cases"], sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if unverified and mode == "strict":
        raise ValueError(
            f"{len(unverified)} intervention twins did not verify; refusing to bill unverified "
            f"invariance claims (first: {unverified[0]})"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True, type=Path, help="campaign pilot_manifest.json")
    parser.add_argument("--out", type=Path, default=None, help="where to write the report")
    parser.add_argument("--mode", choices=MODES, default="advisory")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = verify_manifest_twins(
        manifest, out_path=args.out, mode=args.mode, timeout_seconds=args.timeout_seconds
    )
    print(
        f"twin preflight [{report['policy']}]: {report['group_count']} groups, "
        f"{report['case_count']} cases, unverified {report['unverified_case_count']}"
    )
    return 0 if report["status"] in {"passed", "not_applicable", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
