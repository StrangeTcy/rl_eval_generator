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
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.campaign_progress import read_progress

COMMENT_STATE = "campaign_status_comment.json"


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


def _api(token: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
        value = json.loads(response.read().decode("utf-8"))
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
    if report.get("status"):
        lines.append(f"- **Campaign report:** `{report.get('status')}`")
    lines.extend([
        "",
        "This comment is updated by a fail-open sidecar. It reports persisted campaign metadata only; its failure cannot affect the campaign.",
    ])
    return "\n".join(lines)


def _ensure_comment(output: Path, repository: str, token: str) -> tuple[int, int] | None:
    """Create at most one Issue and then one durable status comment in it."""
    try:
        # The sidecar starts just before the controller creates its output.
        # Persist identity before any API call, or a fast first poll could
        # create an orphaned Issue that a later poll cannot recognize.
        output.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    state_path = output / COMMENT_STATE
    state = _read_json(state_path)
    issue = state.get("issue_number")
    comment = state.get("comment_id")
    if isinstance(issue, int) and isinstance(comment, int):
        return issue, comment
    try:
        if not isinstance(issue, int):
            issue_response = _api(
                token,
                "POST",
                f"/repos/{repository}/issues",
                {
                    "title": "Atria covering campaign live status",
                    "body": "Live campaign status comment created by the workflow sidecar.",
                },
            )
            issue = issue_response.get("number")
            if not isinstance(issue, int):
                return None
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
            return None
        state["issue_number"] = issue
        state["comment_id"] = comment
        state.setdefault("campaign_started_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        _write_json_atomic(state_path, state)
        return issue, comment
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return None


def report_once(output: Path, repository: str, token: str) -> None:
    target = _ensure_comment(output, repository, token)
    if target is None:
        return
    _issue, comment = target
    try:
        _api(token, "PATCH", f"/repos/{repository}/issues/comments/{comment}", {"body": _body(output)})
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return


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
    while True:
        try:
            report_once(args.out, repository, token)
        except Exception:
            # The observer has no campaign-side effect, even on an unexpected
            # serialization/API failure.
            pass
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
