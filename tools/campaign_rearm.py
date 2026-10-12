#!/usr/bin/env python3
"""Ask the runner for the campaign's next leg, from the leg that just banked work.

Why this exists, measured rather than assumed: a resumable pause is only a pause if
something starts the successor. Every pairwise leg ends on the repository's ``13,43 * * * *``
cron, and on 2026-10-12 both pairwise lineages finished a leg at 14:41Z / 14:42Z in a
``max_wall_seconds`` pause with 162 / 416 and 75 / 416 rows persisted, while the cron block
was intact in the deployed ``.github/workflows/`` copies on ``main`` and both workflows
reported ``state: active``. No run was created for hours afterwards - GitHub skips and
delays schedule events, and the repository cannot see or repair that from a workflow file.
The ledgers were safe; the cadence was not, and "dispatch it again" is not a fix.

So a leg that pauses resumably requests its own successor over the REST API with the job
token. Three properties are deliberate:

* It refuses rather than spins, on the same terms the covering campaign's CHAIN already uses, so
  one repo does not grow two scheduler workarounds: a ``max_wall_seconds`` pause hands over at
  once, every other resumable pause waits 10 minutes, chaining stops after 40 legs, and a leg
  that was cancelled, that regressed its state upload, or that left a ``wrapper_failed.json``
  marker never continues. If the API cannot be read it refuses too, because "is a leg already
  running?" is exactly the question the answer is needed for.
* It never reddens a leg. Every failure path prints the reason and exits 0: a broken re-arm
  must cost one missed tick, not a red campaign and a paused ledger. The cron stays as the
  fallback, so this is additive.
* It cannot change what may bill. The dispatched inputs are ``ref`` and the launcher's own
  ``resume_previous: true`` default - never ``rebase_onto_ref``, never an execution mode. A
  re-arm resumes the lineage at its pinned commit; promoting gates-only to paid, or moving the
  code, remains an explicit human dispatch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.campaign_supervisor import RESUMABLE_PAUSE_REASONS  # noqa: E402

BUSY_RUN_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


DEFAULT_COOLDOWN_SECONDS = 600
IMMEDIATE_HANDOVER_REASONS = {"max_wall_seconds"}


def cooldown_seconds_for(reason: str) -> int:
    """How long the group must sit idle before a successor is asked for.

    A leg that ran out of wall time has nothing wrong with it, so it hands over at once; every
    other resumable pause is a provider or case failure that must not be re-attempted immediately
    (10 minutes), which is the bound the covering campaign's CHAIN already uses.
    """
    return 0 if str(reason) in IMMEDIATE_HANDOVER_REASONS else DEFAULT_COOLDOWN_SECONDS


def decide_rearm(
    report,
    *,
    newest_run,
    now: datetime,
    min_interval_seconds: int | None = None,
    workflow_state: str | None,
    token_present: bool,
    chain_depth: int = 0,
    max_chain_depth: int = 40,
    marker_paths=(),
    stage_failed: bool = False,
    was_cancelled: bool = False,
) -> tuple[bool, str]:
    """Return (dispatch?, reason). Pure: no network, no clock, no filesystem, so every branch
    is testable. Order matters: the stops a human would use are checked first, so a cancelled
    leg or a regressed upload cannot be talked into a successor by a report written before it."""
    if was_cancelled:
        return False, "this leg was cancelled; a cancelled leg is the documented way to stop the chain"
    if stage_failed:
        return False, "the state upload was refused because the checkpoint regressed; never continue from a regressed state"
    for marker in marker_paths:
        if marker and os.path.exists(marker):
            return False, f"terminal marker {os.path.basename(marker)} is present, so the campaign stopped on purpose"
    if not isinstance(report, Mapping) or not report:
        return False, "no campaign report was written, so there is nothing to prove a resumable pause"
    status = str(report.get("status") or "")
    if status != "paused":
        return False, f"campaign status is {status!r}; only a paused lineage re-arms"
    reason = str(report.get("pause_reason") or "")
    resumable = report.get("resumable")
    if not isinstance(resumable, bool):
        resumable = reason in RESUMABLE_PAUSE_REASONS
    if not resumable:
        return False, f"pause_reason={reason!r} is not resumable; a successor leg would refuse this state"
    if chain_depth >= max_chain_depth:
        return False, (
            f"chain_depth={chain_depth} reached the cap of {max_chain_depth}; cron remains the only "
            "successor from here, and a human dispatch resets the count"
        )
    if not token_present:
        return False, "no GITHUB_TOKEN in the environment, so no dispatch can be authorized"
    if workflow_state not in (None, "active"):
        return False, (
            f"workflow state is {workflow_state!r}; GitHub will not start a run, and a refused "
            "dispatch here would be indistinguishable from a successful one"
        )
    if newest_run is None:
        return False, "the workflow's run list could not be read; refusing to dispatch blind"
    run_status = str(newest_run.get("status") or "")
    if run_status in BUSY_RUN_STATUSES:
        return False, f"a leg is already {run_status}; the concurrency group would only queue another"
    started = _parse_timestamp(newest_run.get("updated_at")) or _parse_timestamp(newest_run.get("created_at"))
    if started is None:
        return False, "the most recent leg carries no readable timestamp"
    floor = cooldown_seconds_for(reason) if min_interval_seconds is None else int(min_interval_seconds)
    age = int((now - started).total_seconds())
    if age < floor:
        return False, (
            f"the most recent leg ended {age} s ago, below the {floor} s cooldown for "
            f"pause_reason={reason!r}; cron is the fallback"
        )
    return True, f"pause_reason={reason!r} after a {age} s idle gap at chain_depth={chain_depth}"


def _request(url: str, token: str | None, *, data: bytes | None = None, method: str | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "campaign-rearm")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:  # a 403/422 is information, not a crash
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return exc.code, {"message": body[:200]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"message": f"{type(exc).__name__}: {exc}"}


def find_workflow(api: str, repo: str, token: str | None, name: str) -> tuple[dict | None, dict | None]:
    """Resolve the workflow by *name*, so the launcher needs no hardcoded file path or id."""
    status, body = _request(f"{api}/repos/{repo}/actions/workflows?per_page=100", token)
    if status != 200:
        return None, {"error": f"workflow list returned HTTP {status}: {str(body.get('message'))[:120]}"}
    for entry in body.get("workflows") or []:
        if str(entry.get("name")) == name:
            return entry, None
    return None, {"error": f"no workflow named {name!r} in {repo}"}


def successor_inputs(ref: str, chain_depth: int) -> dict[str, Any]:
    """Exactly the manual click, plus the counter the cap reads. Nothing else.

    ``rebase_onto_ref`` is never set here, and no execution mode is passed, so a chained leg can
    only resume what is already authorized to bill.
    """
    inputs: dict[str, Any] = {"resume_previous": True, "chain_depth": str(int(chain_depth) + 1)}
    if ref:
        inputs["ref"] = ref
    return inputs


def dispatch_next_leg(api: str, repo: str, token: str | None, workflow_id: Any, ref: str,
                      chain_depth: int = 0) -> tuple[bool, str]:
    inputs = successor_inputs(ref, chain_depth)
    payload = json.dumps({"inputs": inputs}).encode("utf-8")
    status, body = _request(
        f"{api}/repos/{repo}/actions/workflows/{workflow_id}/dispatches",
        token,
        data=payload,
        method="POST",
    )
    if status in (200, 201, 202, 204):
        return True, f"dispatch accepted (HTTP {status}) with inputs {sorted(inputs)}"
    return False, f"dispatch refused (HTTP {status}): {str(body.get('message'))[:180]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True, help="path to the leg's campaign_report.json")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/name")
    parser.add_argument("--workflow", default=os.environ.get("GITHUB_WORKFLOW", ""), help="workflow display name")
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--ref", default="", help="ref to pin the successor run's checkout to (optional)")
    parser.add_argument(
        "--min-interval-seconds",
        type=int,
        default=None,
        help="override the reason-graded cooldown with a single floor",
    )
    parser.add_argument("--chain-depth", type=int, default=0, help="this leg's chain_depth input")
    parser.add_argument("--max-chain-depth", type=int, default=40, help="stop chaining after this many legs")
    parser.add_argument("--marker", action="append", default=[], dest="markers",
                        help="path whose presence means the campaign stopped on purpose (repeatable)")
    parser.add_argument("--stage-failed", action="store_true", help="the state upload was refused as a regression")
    parser.add_argument("--cancelled", action="store_true", help="this leg was cancelled")
    parser.add_argument("--dry-run", action="store_true", help="print the decision without dispatching")
    args = parser.parse_args(argv)

    api = args.api_url.rstrip("/")
    token = os.environ.get("GITHUB_TOKEN") or ""
    report: Mapping[str, Any] | None = None
    try:
        with open(args.report, "r", encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"campaign re-arm skipped: report unreadable ({type(exc).__name__}: {exc})")
        report = None

    newest_run: Mapping[str, Any] | None = None
    workflow: dict | None = None
    if report and report.get("status") == "paused" and token:
        workflow, lookup_error = find_workflow(api, args.repo, token or None, args.workflow)
        if lookup_error:
            print(f"campaign re-arm skipped: {lookup_error['error']}")
        else:
            status, body = _request(
                    f"{api}/repos/{args.repo}/actions/workflows/{workflow['id']}/runs?per_page=1", token or None
                )
            runs = (body.get("workflow_runs") or []) if status == 200 else []
            newest_run = runs[0] if runs else None

    decision, reason = decide_rearm(
        report,
        newest_run=newest_run,
        now=datetime.now(timezone.utc),
        min_interval_seconds=args.min_interval_seconds,
        workflow_state=(str(workflow["state"]) if workflow else None),
        token_present=bool(token),
        chain_depth=args.chain_depth,
        max_chain_depth=args.max_chain_depth,
        marker_paths=args.markers,
        stage_failed=args.stage_failed,
        was_cancelled=args.cancelled,
    )
    if not decision:
        print(f"campaign re-arm skipped: {reason}")
        return 0
    if args.dry_run:
        print(f"campaign re-arm would dispatch: {reason} (dry run)")
        return 0
    ok, detail = dispatch_next_leg(api, args.repo, token or None, workflow["id"], args.ref, args.chain_depth)
    line = f"campaign re-arm {reason} -> {detail}"
    print(f"::notice::{line}" if ok else f"warning: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
