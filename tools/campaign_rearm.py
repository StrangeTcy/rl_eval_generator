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
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.campaign_supervisor import (  # noqa: E402
    RESUMABLE_PAUSE_REASONS,
    RESUME_BACKOFF_SECONDS,
)

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
    """The *self-imposed* floor: how long the group sits idle before a successor is asked for.

    ``max_wall_seconds`` has nothing wrong with it and needs no extra courtesy wait; every other
    resumable pause is a provider or case failure that waits 10 minutes first, matching the covering
    campaign's CHAIN. What actually governs is ``RESUME_BACKOFF_SECONDS`` below: the successor leg
    runs ``campaign_supervisor.decide_tick``, which answers ``mode="none"`` to any resume attempted
    inside the supervisor's own backoff window (``tools/campaign_supervisor.py:285-292``, no bypass
    flag exists there), and a refused leg does not re-arm either - so dispatching early does not
    resume early, it just ends the chain. This is why the floor is the maximum of the two.
    """
    return 0 if str(reason) in IMMEDIATE_HANDOVER_REASONS else DEFAULT_COOLDOWN_SECONDS


def effective_floor_seconds(reason: str, override: int | None = None) -> int:
    base = cooldown_seconds_for(reason) if override is None else max(0, int(override))
    return max(base, int(RESUME_BACKOFF_SECONDS))


# The leg that just finished is the only actor that can wait for nothing: the paid work is over, and
# a successor dispatched inside the supervisor's window is refused and does not re-arm. So the wait
# happens HERE, in the last step, instead of being pushed onto cron (hours away) or onto a leg that
# will decline. This is the other half of `0e8cb71`: refusing to dispatch early was right, and it also
# meant never dispatching - a `paused` lineage whose leg ended 3 s ago was left to the schedule.
SLEEP = time.sleep
DEFAULT_SLEEP_CAP = 1800


def _floor_state(report: object, newest_run: object, now: datetime,
                 min_interval_seconds: int | None = None) -> tuple[int, int] | None:
    """(floor, age) for the waiting window, or None when the window is not what is being decided."""
    if not isinstance(report, Mapping) or not report or not isinstance(newest_run, Mapping):
        return None
    if str(report.get("status") or "") != "paused":
        return None
    reason = str(report.get("pause_reason") or "")
    resumable = report.get("resumable")
    if not isinstance(resumable, bool):
        resumable = reason in RESUMABLE_PAUSE_REASONS
    if not resumable:
        return None
    started = _parse_timestamp(newest_run.get("updated_at")) or _parse_timestamp(newest_run.get("created_at"))
    if started is None:
        return None
    return effective_floor_seconds(reason, min_interval_seconds), int((now - started).total_seconds())


def handover_wait(report: object, newest_run: object, now: datetime, *,
                  min_interval_seconds: int | None = None,
                  sleep_cap: int | None = DEFAULT_SLEEP_CAP) -> int:
    """Seconds this leg should sit before asking, or 0 when no wait could make a successor acceptable."""
    state = _floor_state(report, newest_run, now, min_interval_seconds)
    if state is None:
        return 0
    floor, age = state
    wait = int(floor - age)
    if wait <= 0:
        return 0
    if sleep_cap is not None and wait > int(sleep_cap):
        return 0
    return wait


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
    sleep_cap: int | None = DEFAULT_SLEEP_CAP,
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
    floor = effective_floor_seconds(reason, min_interval_seconds)
    age = int((now - started).total_seconds())
    if age < floor:
        governing = (
            "the supervisor's own resume backoff"
            if RESUME_BACKOFF_SECONDS >= cooldown_seconds_for(reason)
            else f"the cooldown for pause_reason={reason!r}"
        )
        wait = int(floor - age)
        capped = sleep_cap is not None and wait > int(sleep_cap)
        return False, (
            f"the most recent leg ended {age} s ago, below the {floor} s floor set by {governing}; "
            "a successor dispatched now would be refused with mode=none and would not re-arm"
            + (f" - and sitting it out is off: a {wait} s wait exceeds --sleep-cap={sleep_cap}" if capped else "")
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
    parser.add_argument("--sleep-cap", type=int, default=DEFAULT_SLEEP_CAP,
                        help="longest wait this leg will sit out so a successor is accepted (0 disables waiting)")
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

    now = datetime.now(timezone.utc)
    decision, reason = decide_rearm(
        report,
        newest_run=newest_run,
        now=now,
        sleep_cap=args.sleep_cap,
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
        # The refusal may be purely temporal, in which case the fix is to 🙊, not to hand the
        # campaign back to a schedule that delivered three ticks today.
        🙊 = handover_🙊(report, newest_run, now, min_interval_seconds=args.min_interval_seconds,
                             sleep_cap=args.sleep_cap)
        if 🙊:
            print(f"campaign re-arm: a successor would be refused for another {🙊} s, so this leg "
                  f"is sitting it out before dispatching", flush=True)
            SLEEP(🙊 + 1)
            decision, reason = decide_rearm(
                report,
                newest_run=newest_run,
                now=now + timedelta(seconds=🙊 + 1),
                sleep_cap=args.sleep_cap,
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
        # A decline is a decision, and it must not live only in a log nobody opens: like the refused-tick
        # announcement, this reaches the Checks UI and the jobs API.
        print(f"campaign re-arm skipped: {reason}")
        print(f"::warning::campaign re-arm declined: {reason}")
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
