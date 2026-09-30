#!/usr/bin/env python3
"""Fail-open GitHub Issue status sidecar for a running Atria campaign.

The workflow starts this process in the background beside the controller. It
polls only durable, metadata-only campaign files and replaces one Issue comment
at a fixed interval. API errors are swallowed: the sidecar must never affect
campaign execution or its exit status.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.campaign_progress import read_progress  # noqa: E402
try:  # The sidecar is fail-open: it must import even if the controller cannot.
    from tools.run_suite import MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES  # noqa: E402
except Exception:  # pragma: no cover - defensive, mirrors run_suite's constant
    MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES = 10

COMMENT_STATE = "campaign_status_comment.json"
STATUS_ISSUE_TITLE = "Atria covering campaign live status"
# Optional explicit pin for the status Issue, as a bare number in a one-line
# file. Set it when a campaign must report into an Issue that already exists
# (one that an operator is following, or one opened before a restore). The file
# is read from the checked-out ref, so it travels with the code rather than
# with the state artifact, which is what makes it usable on a campaign whose
# restored state predates the Issue it should report into.
STATUS_ISSUE_PIN = "experiments/atria_status_issue.txt"
# The sidecar is fail-open by construction: it swallows every API error so it
# can never affect the campaign. That silence also made its own death
# undiagnosable -- a killed process and a permanently 403-ing one look
# identical from outside, because both simply stop changing the comment. The
# heartbeat is the missing failure channel: it is rewritten locally every
# cycle, needs no network, and rides along in the uploaded state artifact, so
# "did the observer die, and why" is answerable after the fact.
HEARTBEAT = "campaign_status_heartbeat.json"
# The workflow's cleanup trap runs a second, --once invocation. It must not
# overwrite the periodic observer's record, which is the forensic evidence of
# how the long-running process fared.
FINAL_HEARTBEAT = "campaign_status_heartbeat_final.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    try:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        return


def _api_any(
    token: str, method: str, path: str, payload: dict[str, Any] | None = None
) -> Any:
    """Perform an API call and return the decoded JSON whatever its type.

    Most endpoints answer with an object, but the Issues list endpoint answers
    with an array, and the old _api could not express that: it coerced every
    non-dict response to {} and so could not see a listing at all.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        "https://api.github.com" + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _api(token: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    value = _api_any(token, method, path, payload)
    return value if isinstance(value, dict) else {}


def _elapsed(started_at: Any) -> str:
    if not isinstance(started_at, str):
        return "—"
    try:
        seconds = max(0, int((datetime.now(UTC) - datetime.fromisoformat(started_at.replace("Z", "+00:00"))).total_seconds()))
    except ValueError:
        return "—"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def _progress_bar(completed: int, total: int, width: int = 20) -> str | None:
    """Render an informational Unicode bar without changing the raw counts."""
    if total <= 0 or completed < 0:
        return None
    filled = min(width, (completed * width) // total)
    return "█" * filled + "░" * (width - filled)


def _retry_summary(checkpoint: dict[str, Any], report: dict[str, Any]) -> str | None:
    """Return only aggregate retry metadata; never expose diagnostics or payloads."""
    parts: list[str] = []
    infrastructure = checkpoint.get("infrastructure_retries")
    if isinstance(infrastructure, dict):
        retries = sum(value for value in infrastructure.values() if isinstance(value, int))
        if retries:
            parts.append(f"infrastructure {retries}")
    provider_outage = checkpoint.get("provider_outage") or report.get("provider_outage")
    if isinstance(provider_outage, dict):
        retries = provider_outage.get("retries")
        waited = provider_outage.get("waited_seconds")
        if isinstance(retries, int):
            suffix = f" ({waited}s waited)" if isinstance(waited, (int, float)) else ""
            parts.append(f"provider outage {retries}{suffix}")
    for field, label in (
        ("runtime_failures", "Docker"),
        ("wrapper_transient_failures", "wrapper"),
    ):
        value = checkpoint.get(field, report.get(field))
        if isinstance(value, int) and value:
            parts.append(f"{label} {value}")
    return "; ".join(parts) or None


def _infrastructure_detail(checkpoint: dict[str, Any]) -> list[str]:
    """Name the cases holding an infrastructure-retry budget, and how much is left.

    An ``infrastructure_error`` pause is resumable only while a case stays under
    ``MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES``; past that the campaign stops for an
    operator. Without this, the case about to exhaust its budget is visible only
    inside the state artifact. Only durable metadata is reported: the case id, the
    integer count, and the controller's own short, pre-redacted ``error`` string.
    Never stdout/stderr tails.
    """
    ledger = checkpoint.get("infrastructure_retries")
    if not isinstance(ledger, dict):
        return []
    pending = sorted(
        ((str(case), int(count)) for case, count in ledger.items() if isinstance(count, int) and count > 0),
        key=lambda item: (-item[1], item[0]),
    )
    if not pending:
        return []
    errors: dict[str, str] = {}
    results = checkpoint.get("results")
    if isinstance(results, list):
        for row in results:
            if not isinstance(row, dict):
                continue
            case_id = row.get("case_id")
            error = row.get("error")
            if isinstance(case_id, str) and isinstance(error, str) and error:
                errors[case_id] = error[:160]
    lines = ["- **Infrastructure retries by case:**"]
    for case_id, count in pending[:5]:
        remaining = MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES - count
        budget = (
            f"{remaining} automatic retr{'y' if remaining == 1 else 'ies'} left"
            if remaining > 0
            else "budget exhausted, stops for an operator"
        )
        detail = f" — {errors[case_id]}" if case_id in errors else ""
        lines.append(f"  - `{case_id}`: {count}/{MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES} ({budget}){detail}")
    if len(pending) > 5:
        lines.append(f"  - …and {len(pending) - 5} more")
    return lines


def _body(output: Path) -> str:
    progress = read_progress(output)
    checkpoint = _read_json(output / "suite_checkpoint.json")
    partial = _read_json(output / "instance_oracles_partial.json")
    report = _read_json(output / "campaign_report.json")
    state = _read_json(output / COMMENT_STATE)
    run = checkpoint.get("run")
    run = run if isinstance(run, dict) else {}
    phase = str(progress.get("phase") or "starting")
    current = progress.get("current_case") or run.get("active_case_id") or "—"
    status = str(report.get("status") or run.get("execution_state") or "in progress")
    campaign_started_at = checkpoint.get("started_at") or state.get("campaign_started_at")
    lines = [
        "## Atria campaign live status",
        "",
        f"- **Updated:** {progress.get('updated_at') or report.get('updated_at') or datetime.now(UTC).isoformat()}",
        f"- **Campaign state:** `{status}`",
        f"- **Campaign elapsed:** {_elapsed(campaign_started_at)}",
        f"- **Phase:** `{phase}`",
        f"- **Current case:** `{current}`",
        f"- **Current elapsed:** {_elapsed(progress.get('current_started_at'))}",
    ]
    if phase == "exact-instance gate" or partial:
        completed = progress.get("gate_completed")
        if not isinstance(completed, int):
            rows = partial.get("rows")
            completed = len(rows) if isinstance(rows, dict) else 0
        total = progress.get("gate_total")
        lines.append(f"- **Gate checkpointed:** `{completed} / {total if isinstance(total, int) else '?'}`")
        if isinstance(total, int):
            bar = _progress_bar(completed, total)
            if bar is not None:
                lines.append(f"- **Gate progress:** `{bar}`")
    if phase == "episodes" or checkpoint:
        results = checkpoint.get("results")
        completed = progress.get("episodes_completed")
        if not isinstance(completed, int):
            completed = len(results) if isinstance(results, list) else 0
        total = progress.get("episodes_total") or checkpoint.get("manifest_case_count")
        lines.append(f"- **Episodes checkpointed:** `{completed} / {total if isinstance(total, int) else '?'}`")
        if isinstance(total, int):
            bar = _progress_bar(completed, total)
            if bar is not None:
                lines.append(f"- **Episodes progress:** `{bar}`")
    pause_reason = progress.get("pause_reason") or checkpoint.get("pause_reason") or report.get("pause_reason")
    if pause_reason:
        lines.append(f"- **Pause reason:** `{pause_reason}`")
    retry_summary = _retry_summary(checkpoint, report)
    if retry_summary:
        lines.append(f"- **Retries:** `{retry_summary}`")
    lines.extend(_infrastructure_detail(checkpoint))
    if report.get("status"):
        lines.append(f"- **Campaign report:** `{report.get('status')}`")
    lines.extend([
        "",
        "This comment is updated by a fail-open sidecar. It reports persisted campaign metadata only; its failure cannot affect the campaign.",
    ])
    return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _describe_error(exc: BaseException) -> str:
    """Summarize a failure without leaking request payloads or credentials.

    The token travels in a header, never in the URL or these fields, so code
    and reason are safe to persist. The result is truncated because it lands
    in an artifact an operator reads, not a log.
    """
    if isinstance(exc, urllib.error.HTTPError):
        description = f"HTTPError {exc.code} {exc.reason}"
    elif isinstance(exc, urllib.error.URLError):
        description = f"URLError {exc.reason}"
    else:
        description = f"{type(exc).__name__}: {exc}"
    return description[:200]


def _write_heartbeat(output: Path, state: dict[str, Any]) -> None:
    """Persist observer liveness. Best-effort: never raises, never blocks."""
    try:
        output.mkdir(parents=True, exist_ok=True)
        name = FINAL_HEARTBEAT if state.get("role") == "final" else HEARTBEAT
        _write_json_atomic(output / name, state)
    except Exception:
        return


def _pinned_issue_number() -> int | None:
    """The Issue number pinned in STATUS_ISSUE_PIN, or None if absent/invalid."""
    try:
        raw = (ROOT / STATUS_ISSUE_PIN).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    raw = raw.lstrip("#").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _newest_open_status_issue(token: str, repository: str) -> int | None:
    """Reuse the most recently opened live-status Issue, if there is one.

    The sidecar used to create a new Issue unconditionally whenever the restored
    state carried no issue number, so every dispatch of a campaign whose state
    predates a given Issue opened another one. A campaign being watched in one
    Issue then scattered its status across a new Issue per leg, and the number
    an operator was following went silent. Reusing the newest open Issue keeps a
    single campaign's status in one place across restores.
    """
    listing = _api_any(
        token,
        "GET",
        f"/repos/{repository}/issues?state=open&sort=created&direction=desc&per_page=100",
    )
    if not isinstance(listing, list):
        return None
    for entry in listing:
        if not isinstance(entry, dict) or entry.get("pull_request"):
            continue
        if entry.get("title") != STATUS_ISSUE_TITLE:
            continue
        number = entry.get("number")
        if isinstance(number, int):
            return number
    return None


def _ensure_comment(
    output: Path, repository: str, token: str
) -> tuple[tuple[int, int] | None, str | None]:
    """Create at most one Issue and then one durable status comment in it.

    Returns ``(identity, error)``. The error is propagated rather than
    swallowed so the heartbeat can distinguish "refused by the API" from
    "never ran"; the function itself still never raises.
    """
    try:
        # The sidecar starts just before the controller creates its output.
        # Persist identity before any API call, or a fast first poll could
        # create an orphaned Issue that a later poll cannot recognize.
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, _describe_error(exc)
    state_path = output / COMMENT_STATE
    state = _read_json(state_path)
    issue = state.get("issue_number")
    comment = state.get("comment_id")
    if isinstance(issue, int) and isinstance(comment, int):
        return (issue, comment), None
    try:
        if not isinstance(issue, int):
            # Prefer an explicitly pinned Issue, then an existing open one, and
            # only create a new Issue when there is nothing to reuse. Every one
            # of these is best-effort: a failure falls through to the next
            # option, and the sidecar is fail-open regardless.
            issue = _pinned_issue_number() or _newest_open_status_issue(token, repository)
            if not isinstance(issue, int):
                issue_response = _api(
                    token,
                    "POST",
                    f"/repos/{repository}/issues",
                    {
                        "title": STATUS_ISSUE_TITLE,
                        "body": "Live campaign status comment created by the workflow sidecar.",
                    },
                )
                issue = issue_response.get("number")
            if not isinstance(issue, int):
                return None, "Issue selection returned no number"
            # Persist the Issue before creating its comment. If the comment API
            # has a transient failure, a later poll reuses this Issue instead
            # of creating one Issue per retry.
            state = {
                "issue_number": issue,
                "campaign_started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
            _write_json_atomic(state_path, state)
        comment_response = _api(
            token,
            "POST",
            f"/repos/{repository}/issues/{issue}/comments",
            {"body": _body(output)},
        )
        comment = comment_response.get("id")
        if not isinstance(comment, int):
            return None, "comment creation returned no id"
        state["issue_number"] = issue
        state["comment_id"] = comment
        state.setdefault("campaign_started_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        _write_json_atomic(state_path, state)
        return (issue, comment), None
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
        return None, _describe_error(exc)


def report_once(output: Path, repository: str, token: str) -> str | None:
    """Publish one update. Returns None on success, else a short error string.

    The return value is the only change to the contract: the function still
    never raises, so existing callers that ignore it behave exactly as before.
    """
    target, error = _ensure_comment(output, repository, token)
    if target is None:
        return error or "comment identity unavailable"
    _issue, comment = target
    try:
        _api(token, "PATCH", f"/repos/{repository}/issues/comments/{comment}", {"body": _body(output)})
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
        return _describe_error(exc)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument(
        "--wait-for-path",
        type=Path,
        help="wait to create the Issue until this durable controller marker exists",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="publish one final best-effort update and exit",
    )
    args = parser.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        return 0
    interval = max(15.0, float(args.interval_seconds))
    if args.wait_for_path is not None and not args.once:
        # A fresh dispatch removes stale output before it writes its intent.
        # Waiting prevents the observer from persisting a new Issue identity
        # into that directory just before the controller deliberately resets it.
        while not args.wait_for_path.exists():
            time.sleep(min(5.0, interval))
    heartbeat: dict[str, Any] = {
        "schema_version": 1,
        "role": "final" if args.once else "periodic",
        "pid": os.getpid(),
        "started_at": _utc_now(),
        "interval_seconds": interval,
        "cycles": 0,
        "published": 0,
        "failures": 0,
        "consecutive_failures": 0,
        "last_published_at": None,
        "last_error": None,
        "last_error_at": None,
    }
    while True:
        heartbeat["cycles"] += 1
        heartbeat["updated_at"] = _utc_now()
        try:
            error = report_once(args.out, repository, token)
        except Exception as exc:  # noqa: BLE001
            # The observer has no campaign-side effect, even on an unexpected
            # serialization/API failure.
            error = _describe_error(exc)
        if error is None:
            heartbeat["published"] += 1
            heartbeat["last_published_at"] = heartbeat["updated_at"]
            heartbeat["consecutive_failures"] = 0
        else:
            heartbeat["failures"] += 1
            heartbeat["consecutive_failures"] += 1
            heartbeat["last_error"] = error
            heartbeat["last_error_at"] = heartbeat["updated_at"]
        # Written after every cycle, including failing ones. A heartbeat whose
        # updated_at stops advancing means the process itself is gone; one that
        # keeps advancing while consecutive_failures climbs means the process
        # is alive and the GitHub API is refusing it. Those two were previously
        # indistinguishable.
        _write_heartbeat(args.out, heartbeat)
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
