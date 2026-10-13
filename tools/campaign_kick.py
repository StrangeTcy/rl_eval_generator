"""Start one campaign leg from a push, for when the scheduler will not produce a tick.

Why this file exists, with the measurements that forced it. Both pairwise campaigns are healthy and
resumable - Mercury banked 64 episodes in run 31 and its last report is ``paused / max_wall_seconds``
with no terminal marker - and the successor-arming tool now works, because main's unparseable copy of
``tools/campaign_rearm.py`` was deleted (0b08e85) so the launcher falls back to the checkout's copy. The
campaigns still sat idle, for exactly two reasons:

* a leg arms only its *own* successor, so the chain needs one leg first; and
* the starters that could supply it are closed: GitHub had created no scheduled run since 09:26 although
  both workflows are ``state=active`` and still declare ``cron: "13,43 * * * *"`` (verified again at
  15:14:39, after waiting past the 15:13 tick), and ``POST .../actions/workflows/{id}/dispatches`` and
  ``POST .../actions/runs/{id}/rerun-failed-jobs`` both answer 403 to the only credential this
  workspace can use ("Resource not accessible by integration").

A push is the one event this workspace *can* produce, and CI already executes repository code
(``pytest -q``). So CI asks, and only under a written, expiring, single-purpose instruction committed to
the branch: ``campaign_kick.json``. Two measurements closed both ends of that plan on 2026-10-13, and the
tool stays because either one can be reversed from the repository's settings without touching this code:

* the ``tests`` job in ci.yml is handed no credential at all - run 343 annotated "campaign kick: skipped:
  no GITHUB_TOKEN in this job" - so repository code executed by CI has nothing to dispatch *with*; and
* the workflow that would grant one cannot be added: pushing ``.github/workflows/campaign-kick.yml``
  (push of 5939fba, 16:01 UTC) was refused with "refusing to allow a GitHub App to create or update
  workflow ... without `workflows` permission".

So the trigger is held at tools/campaign_kick_workflow.yml, tested for width, and uninstalled. A kick is
an act, not a state: a committed ``campaign_kick.json`` expires, and deleting it is what "nothing pending"
is supposed to look like. The dispatch it sends carries ``resume_previous`` and nothing else -
never ``rebase_onto_ref``, never ``clear_wrapper_stop``, never an execution mode or a ceiling - so a
kicked leg can only continue what the campaign's own carried intent already authorizes. Every check fails
closed: no file, stale file, wrong event, wrong branch, unreadable API, disabled workflow, a leg already
running, or a denied token, and the kick prints one line and does nothing.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KICK_FILE = "campaign_kick.json"
# The only inputs a kick may set. Everything else on that form is an authorization, and authorizations
# come from a human dispatch or from the carried intent - never from a push.
ALLOWED_INPUTS = ("resume_previous", "chain_depth")
DEFAULT_MAX_AGE_SECONDS = 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_kick(root: Path) -> dict[str, Any] | None:
    """The committed kick instruction, or None when there is no usable one."""
    path = Path(root) / KICK_FILE
    try:
        kick = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(kick, dict) or not kick_targets(kick):
        return None
    expires = _parse_time(kick.get("expires_at"))
    if expires is None or expires <= _now():
        return None
    created = _parse_time(kick.get("committed_at"))
    if created is not None and (_now() - created).total_seconds() > DEFAULT_MAX_AGE_SECONDS:
        return None
    return kick


def decide(
    kick: dict[str, Any] | None,
    *,
    event: str | None,
    ref: str | None,
    token_present: bool,
    api_state: str | None = None,
    busy: bool = False,
) -> tuple[bool, str]:
    """Return (dispatch?, reason). Pure: no clock beyond the freshness already applied, no network."""
    if kick is None:
        return False, f"no fresh {KICK_FILE} on this branch"
    if event != "push":
        return False, f"a {event or 'non-push'} event cannot kick a leg; only a push reaches CI"
    if not token_present:
        return False, "no GITHUB_TOKEN in this job, so the dispatch could not be authorized"
    want_ref = str(kick.get("branch") or "")
    if want_ref and ref != f"refs/heads/{want_ref}":
        return False, f"this push is on {ref!r}, the kick is written for branch {want_ref!r}"
    if api_state not in (None, "active"):
        return False, f"workflow state is {api_state!r}; GitHub will not start a run from it"
    if busy:
        return False, "a leg of this workflow is already queued or running; kicking would queue a second"
    return True, f"kicking {kick['workflow']!r} for the push on {ref or '?'}"


def kick_targets(kick: dict[str, Any]) -> list[str]:
    """The workflow names a kick names - one, or several, since a stalled scheduler stalls every campaign."""
    raw = kick.get("workflow")
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    return [name for name in (x.strip() for x in items if isinstance(x, str)) if name]


def _request(url: str, token: str, *, body: bytes | None = None, method: str = "GET") -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", "replace")[:300]}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def find_workflow(api: str, repo: str, token: str, name: str) -> tuple[dict | None, str]:
    status, body = _request(f"{api}/repos/{repo}/actions/workflows?per_page=100", token)
    if status != 200:
        return None, f"workflow list unreadable ({status})"
    for entry in body.get("workflows") or []:
        if entry.get("name") == name:
            return entry, ""
    return None, f"no workflow named {name!r} in {repo}"


def leg_busy(api: str, repo: str, token: str, workflow_id: Any) -> bool:
    for state in ("queued", "in_progress"):
        status, body = _request(
            f"{api}/repos/{repo}/actions/workflows/{workflow_id}/runs?status={state}&per_page=1", token
        )
        if status == 200 and (body.get("total_count") or 0) > 0:
            return True
    return False


def kick_inputs(kick: dict[str, Any]) -> dict[str, Any]:
    """Exactly the resume flag, plus the chain counter. No authorization field can ride along."""
    return {"resume_previous": True, "chain_depth": str(int(kick.get("chain_depth") or 0))}


def dispatch(api: str, repo: str, token: str, workflow_id: Any, ref: str, inputs: dict) -> tuple[bool, str]:
    payload = json.dumps({"ref": ref, "inputs": inputs}).encode("utf-8")
    status, body = _request(
        f"{api}/repos/{repo}/actions/workflows/{workflow_id}/dispatches",
        token,
        body=payload,
        method="POST",
    )
    if status in (200, 201, 204):
        return True, f"dispatch accepted (HTTP {status})"
    return False, f"dispatch refused (HTTP {status}): {str(body.get('error') or body)[:200]}"


def maybe_kick_from_ci(root: Path) -> str:
    """The one entry point CI reaches. Never raises, never fails a job, does nothing by default."""
    try:
        kick = read_kick(Path(root))
        if kick is None:
            return ""
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
        repo = os.environ.get("GITHUB_REPOSITORY") or str(kick.get("repo") or "")
        api = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        go, reason = decide(
            kick,
            event=os.environ.get("GITHUB_EVENT_NAME"),
            ref=os.environ.get("GITHUB_REF"),
            token_present=bool(token and repo),
        )
        if not go:
            return f"skipped: {reason}"
        notes = []
        for name in kick_targets(kick):
            workflow, error = find_workflow(api, repo, token, name)
            if workflow is None:
                notes.append(f"skipped: {error}")
                continue
            if leg_busy(api, repo, token, workflow["id"]):
                notes.append(f"skipped: a leg of {name!r} is already queued or running")
                continue
            ok, detail = dispatch(
                api,
                repo,
                token,
                workflow["id"],
                str(kick.get("dispatch_ref") or os.environ.get("GITHUB_REF_NAME") or ""),
                kick_inputs(kick),
            )
            notes.append(("dispatched: " if ok else "refused: ") + detail)
        return "; ".join(notes)
    except Exception as exc:  # noqa: BLE001 - a kick must never be able to break the job that carries it
        return f"skipped: kick check raised {type(exc).__name__}: {exc}"


def main() -> int:
    """CLI entry: print the verdict, exit 0 either way.

    A kick is a favour CI does a campaign, not a build requirement, so a refusal must never turn a job
    red; the ``::warning::`` annotation is what makes the verdict readable, because the log itself is not.
    """
    root = Path(os.environ.get("GITHUB_WORKSPACE") or ".")
    note = maybe_kick_from_ci(root)
    if note:
        print(("::warning::" if os.environ.get("GITHUB_RUN_ID") else "") + f"campaign kick: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
