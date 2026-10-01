#!/usr/bin/env python3
"""Summarize a finished (or paused) Atria covering-campaign state directory.

Input is the newest ``atria-campaign-state-N`` artifact, unzipped. Each leg
uploads the WHOLE ``runs/atria_campaign`` directory (restored state plus what
it added), so the newest artifact is already the merged result; there is nothing
to merge. This tool reads it, provider-free and read-only, and answers two
questions:

* Was anything dropped? It reconciles the served manifest, the omissions the
  campaign recorded loudly (unsupported modality, known gate-blocked cases),
  and the result rows actually present.
* Is a score believable? It prints per-environment outcomes and flags patterns
  that usually mean the harness, not the model, produced them.

Usage:
    python tools/summarize_campaign.py STATE_DIR [--csv merged_results.csv]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _final_from_tail(row: dict[str, Any]) -> dict[str, Any]:
    """Best-effort: pull the judge's ``final`` object out of the stored stdout tail."""
    text = row.get("stdout_tail") or ""
    decoder = json.JSONDecoder()
    best: dict[str, Any] = {}
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("final"), dict):
            best = value["final"]
    return best


def reconcile(state: Path, rows: list[dict[str, Any]], checkpoint: dict[str, Any]) -> list[str]:
    report = _load(state / "campaign_report.json") or {}
    manifest = _load(state / "pilot_manifest.json") or {}
    manifest_ids = [str(c.get("case_id")) for c in manifest.get("cases", []) if isinstance(c, dict)]
    row_ids = [str(r.get("case_id")) for r in rows]
    dupes = sorted(k for k, v in Counter(row_ids).items() if v > 1)
    omitted: dict[str, list[str]] = {}
    for key in ("campaign_omissions", "known_gate_blocked_omissions"):
        block = report.get(key) or {}
        ids = block.get("omitted_case_ids") if isinstance(block, dict) else None
        if ids:
            omitted[key] = [str(i) for i in ids]
    omitted_all = {i for ids in omitted.values() for i in ids}
    lines = [
        "== Reconciliation ==",
        f"manifest_case_count (checkpoint) : {checkpoint.get('manifest_case_count')}",
        f"cases in pilot_manifest.json     : {len(manifest_ids) or 'n/a'}",
        f"result rows recorded             : {len(rows)} ({len(set(row_ids))} unique case ids)",
        f"campaign status / pause          : {report.get('status')} / {checkpoint.get('pause_reason')}",
    ]
    for key, ids in omitted.items():
        lines.append(f"omitted, recorded in report ({key}): {len(ids)}")
    if dupes:
        lines.append(f"!! duplicate rows for: {dupes}")
    if manifest_ids:
        missing = [i for i in manifest_ids if i not in set(row_ids) and i not in omitted_all]
        extra = [i for i in row_ids if i not in set(manifest_ids)]
        lines.append(f"manifest cases with NO row and NOT in an omission list: {len(missing)}")
        for i in missing[:20]:
            lines.append(f"  !! missing: {i}")
        if extra:
            lines.append(f"rows whose case is not in the manifest: {len(extra)}")
    else:
        lines.append("(pilot_manifest.json not in the artifact; cannot list missing cases)")
    return lines


def per_environment(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    by_env: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_env[str(row.get("environment"))].append(row)
    table = [
        "== Per environment ==",
        f"{'environment':28} {'n':>3} {'scored':>6} {'infra':>5} {'pause':>5} {'PASS':>4} {'FAIL':>4} "
        f"{'mean':>5} {'judge':14} {'med_s':>6} {'med_http':>8}",
    ]
    flags: list[str] = []
    for env in sorted(by_env):
        group = by_env[env]
        scored = [r for r in group if r.get("status") == "scored"]
        verdicts = Counter(str(r.get("verdict")) for r in scored)
        scores = [float(r["score"]) for r in scored if isinstance(r.get("score"), (int, float))]
        guarantee = ",".join(sorted({str(r.get("judge_guarantee", "?")) for r in group}))
        elapsed = [float(r["elapsed_seconds"]) for r in scored if isinstance(r.get("elapsed_seconds"), (int, float))]
        https = [int(r["http_attempts"]) for r in scored if isinstance(r.get("http_attempts"), int)]
        table.append(
            f"{env:28} {len(group):>3} {len(scored):>6} "
            f"{sum(r.get('status') == 'infrastructure_error' for r in group):>5} "
            f"{sum(r.get('status') == 'paused_provider_error' for r in group):>5} "
            f"{verdicts.get('PASS', 0):>4} {verdicts.get('FAIL', 0):>4} "
            f"{(statistics.mean(scores) if scores else float('nan')):>5.2f} {guarantee:14} "
            f"{(statistics.median(elapsed) if elapsed else float('nan')):>6.0f} "
            f"{(statistics.median(https) if https else float('nan')):>8.0f}"
        )
        if len(scored) >= 3 and verdicts.get("PASS", 0) == len(scored) and "compile_only" in guarantee:
            flags.append(f"{env}: {len(scored)}/{len(scored)} PASS under compile_only (its judge was never "
                         "validated against a wrong patch, so a perfect score is not evidence of skill)")
        if len(scored) >= 3 and verdicts.get("FAIL", 0) == len(scored) and "compile_only" in guarantee:
            flags.append(f"{env}: {len(scored)}/{len(scored)} FAIL under compile_only (could be a broken judge, not the model)")
        fast = [r for r in scored if r.get("verdict") == "PASS" and isinstance(r.get("elapsed_seconds"), (int, float))
                and r["elapsed_seconds"] < 10]
        if fast:
            flags.append(f"{env}: {len(fast)} PASS row(s) finished in <10s (did an agent really run?)")
        modes = Counter(str(r.get("failure_mode")) for r in scored if r.get("verdict") == "FAIL")
        protocol = sum(v for k, v in modes.items() if k in {"invalid_action", "not_submitted", "reward_denial"})
        if modes and protocol and protocol >= max(1, len(scored) // 2):
            flags.append(f"{env}: {protocol} of {len(scored)} scored rows failed on protocol/format "
                         f"({dict(modes)}), which measures output format more than the task")
    return table, flags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("state_dir", type=Path)
    parser.add_argument("--csv", type=Path, help="write one flat row per case to this CSV")
    args = parser.parse_args(argv)
    checkpoint = _load(args.state_dir / "suite_checkpoint.json")
    if not isinstance(checkpoint, dict):
        print(f"no readable suite_checkpoint.json in {args.state_dir}", file=sys.stderr)
        return 2
    rows = [r for r in checkpoint.get("results", []) if isinstance(r, dict)]
    print("\n".join(reconcile(args.state_dir, rows, checkpoint)))
    table, flags = per_environment(rows)
    print()
    print("\n".join(table))
    totals = Counter(str(r.get("status")) for r in rows)
    guarantees = Counter(str(r.get("judge_guarantee", "?")) for r in rows if r.get("status") == "scored")
    print(f"\nrow status: {dict(totals)}\nscored rows by judge_guarantee: {dict(guarantees)}")
    print("\n== Flags (things to check before believing a number) ==")
    print("\n".join(f"- {f}" for f in flags) if flags else "- none raised")
    if args.csv:
        fields = ["case_id", "environment", "track", "difficulty", "seed", "status", "verdict", "score",
                  "failure_mode", "judge_guarantee", "elapsed_seconds", "http_attempts", "error"]
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields + ["judge_checks"])
            writer.writeheader()
            for row in rows:
                out = {k: row.get(k) for k in fields}
                out["judge_checks"] = json.dumps(_final_from_tail(row).get("checks", ""))
                writer.writerow(out)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
