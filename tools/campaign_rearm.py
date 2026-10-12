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

* It refuses rather than spins. A dispatch needs the group to be idle *and* the most recent
  leg to be older than ``--min-interval-seconds``, so a fast-failing leg cannot drive the
  scheduler in a loop; and if the API cannot be read, it refuses, because "is a leg already
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


def decide_rearm(
    report: Mapping[str, Any] | None,
    *,
    newest_run: Mapping[str, Any] | None,
    now: datetime,
    min_interval_seconds: int,
    workflow_state: str | None,
    token_present: bool,
) -> tuple[bool, str]:
    """Return (dispatch?, reason). Pure: no network, no clock, so every branch is testable."""
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
    age = int((now - started).total_seconds())
    if age < min_interval_seconds:
        return False, (
            f"the most recent leg ended {age // 60} min ago, below the {min_interval_seconds // 60} min "
            "floor; refusing to spin the scheduler"
        )
    return True, f"pause_reason={reason!r} with the group idle for {age // 60} min"


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


def dispatch_next_leg(api: str, repo: str, token: str | None, workflow_id: Any, ref: str) -> tuple[bool, str]:
    inputs: dict[str, Any] = {"resume_previous": True}
    if ref:
        inputs["ref"] = ref
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
        default=1800,
        help="smallest gap enforced between legs; the floor on spinning the scheduler",
    )
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
    )
    if not decision:
        print(f"campaign re-arm skipped: {reason}")
        return 0
    if args.dry_run:
        print(f"campaign re-arm would dispatch: {reason} (dry run)")
        return 0
    ok, detail = dispatch_next_leg(api, args.repo, token or None, workflow["id"], args.ref)
    line = f"campaign re-arm {reason} -> {detail}"
    print(f"::notice::{line}" if ok else f"warning: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
