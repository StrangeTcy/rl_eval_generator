from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import campaign_kick  # noqa: E402

NOW = datetime(2026, 10, 13, 15, 20, tzinfo=timezone.utc)
BRANCH = "arena/595b91e0-rl-eval-generator"


@pytest.fixture(autouse=True)
def _clock(monkeypatch) -> None:
    monkeypatch.setattr(campaign_kick, "_now", lambda: NOW)


def _kick(root: Path, **overrides) -> None:
    body = {
        "workflow": "Mercury pairwise campaign",
        "branch": BRANCH,
        "dispatch_ref": BRANCH,
        "committed_at": "2026-10-13T15:10:00+00:00",
        "expires_at": "2026-10-13T15:40:00+00:00",
        "reason": "GitHub has created no scheduled tick since 09:26",
    }
    body.update(overrides)
    (root / campaign_kick.KICK_FILE).write_text(json.dumps(body), encoding="utf-8")


def _readable(root: Path) -> dict:
    return campaign_kick.read_kick(root) or {}


def test_no_file_no_kick(tmp_path: Path) -> None:
    assert campaign_kick.read_kick(tmp_path) is None


def test_an_expired_or_stale_instruction_is_not_a_kick(tmp_path: Path) -> None:
    _kick(tmp_path, expires_at="2026-10-13T15:19:00+00:00")
    assert campaign_kick.read_kick(tmp_path) is None, "a kick outside its window must die"
    _kick(tmp_path, expires_at="2026-10-13T16:00:00+00:00", committed_at="2026-10-13T13:00:00+00:00")
    assert campaign_kick.read_kick(tmp_path) is None, "and so must one committed hours before this run"
    _kick(tmp_path, workflow="")
    assert campaign_kick.read_kick(tmp_path) is None, "and one that names no workflow"
    _kick(tmp_path, expires_at="not a time")
    assert campaign_kick.read_kick(tmp_path) is None, "and one whose expiry cannot be parsed"


def test_the_guards_all_refuse_before_anything_is_sent() -> None:
    kick = {"workflow": "Mercury pairwise campaign", "branch": BRANCH}
    cases = [
        ({"event": "push", "ref": f"refs/heads/{BRANCH}", "token_present": True}, "no fresh campaign_kick.json"),
        ({"kick": kick, "event": "schedule", "ref": f"refs/heads/{BRANCH}", "token_present": True},
         "cannot kick a leg"),
        ({"kick": kick, "event": "pull_request", "ref": f"refs/heads/{BRANCH}", "token_present": True},
         "cannot kick a leg"),
        ({"kick": kick, "event": "push", "ref": f"refs/heads/{BRANCH}", "token_present": False},
         "no GITHUB_TOKEN"),
        ({"kick": kick, "event": "push", "ref": "refs/heads/someone-else", "token_present": True},
         "written for branch"),
        ({"kick": kick, "event": "push", "ref": f"refs/heads/{BRANCH}", "token_present": True,
          "api_state": "disabled_manually"}, "workflow state"),
        ({"kick": kick, "event": "push", "ref": f"refs/heads/{BRANCH}", "token_present": True,
          "busy": True}, "already queued or running"),
    ]
    for kwargs, expect in cases:
        passed, reason = campaign_kick.decide(kwargs.pop("kick", None), **kwargs)
        assert passed is False, (expect, reason)
        assert expect in reason, (expect, reason)

    go, reason = campaign_kick.decide(
        kick, event="push", ref=f"refs/heads/{BRANCH}", token_present=True
    )
    assert go is True and "Mercury pairwise campaign" in reason, reason


def test_a_kick_carries_no_authorization_field() -> None:
    """A push may resume what is already authorized, and never more than that.

    `rebase_onto_ref` re-pins a lineage's code, `clear_wrapper_stop` lifts a recorded operator stop, and
    an execution mode or ceiling input authorizes spend - those belong to a human dispatch, and the
    campaign's own tools refuse them from anywhere else. Pinned here so an edit cannot smuggle one into
    the payload by accident.
    """
    inputs = campaign_kick.kick_inputs({"chain_depth": 0})
    assert set(inputs) <= set(campaign_kick.ALLOWED_INPUTS), inputs
    assert inputs["resume_previous"] is True and inputs["chain_depth"] == "0", inputs
    forbidden = ("rebase_onto_ref", "clear_wrapper_stop", "execution_mode", "max_api_calls_override",
                 "max_tokens_total_override", "raise_ceiling", "allow_ceiling_override")
    for name in forbidden:
        assert name not in inputs and name not in campaign_kick.ALLOWED_INPUTS, name


def _wire(monkeypatch, *, statuses) -> list[tuple]:
    calls: list[tuple] = []

    def fake_request(url, token, *, body=None, method="GET"):
        calls.append((method, url, body))
        for needle, value in statuses.items():
            if needle in url:
                return value
        return 200, {}

    monkeypatch.setattr(campaign_kick, "_request", fake_request)
    return calls


def _ci_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", f"refs/heads/{BRANCH}")
    monkeypatch.setenv("GITHUB_REF_NAME", BRANCH)
    monkeypatch.setenv("GITHUB_REPOSITORY", "StrangeTcy/rl_eval_generator")
    monkeypatch.setenv("GITHUB_TOKEN", "token")


def test_the_dispatch_path_starts_one_leg_and_reports_it(tmp_path: Path, monkeypatch) -> None:
    _kick(tmp_path)
    calls = _wire(monkeypatch, statuses={
        "actions/workflows?per_page": (200, {"workflows": [
            {"id": 380866469, "name": "Mercury pairwise campaign", "state": "active"}]}),
        "status=queued": (200, {"total_count": 0}),
        "status=in_progress": (200, {"total_count": 0}),
        "dispatches": (204, {}),
    })
    _ci_env(monkeypatch)
    note = campaign_kick.maybe_kick_from_ci(tmp_path)
    assert note.startswith("dispatched:"), note
    posts = [call for call in calls if call[0] == "POST"]
    assert len(posts) == 1, posts
    payload = json.loads(posts[0][2])
    assert payload["ref"] == BRANCH, payload
    assert set(payload["inputs"]) <= set(campaign_kick.ALLOWED_INPUTS), payload
    assert "/dispatches" in posts[0][1], posts[0][1]


def test_a_busy_workflow_is_not_kicked(tmp_path: Path, monkeypatch) -> None:
    _kick(tmp_path)
    _wire(monkeypatch, statuses={
        "actions/workflows?per_page": (200, {"workflows": [
            {"id": 1, "name": "Mercury pairwise campaign", "state": "active"}]}),
        "status=in_progress": (200, {"total_count": 1}),
        "dispatches": (204, {}),
    })
    _ci_env(monkeypatch)
    note = campaign_kick.maybe_kick_from_ci(tmp_path)
    assert "already queued or running" in note, note
    assert "workflow/1/dispatches" not in note


def test_a_denied_token_and_a_broken_api_are_printed_never_raised(tmp_path: Path, monkeypatch) -> None:
    _kick(tmp_path)
    # A read-only CI token: the workflow list itself is refused.
    _wire(monkeypatch, statuses={
        "actions/workflows?per_page": (403, {"error": "Resource not accessible by integration"}),
    })
    _ci_env(monkeypatch)
    note = campaign_kick.maybe_kick_from_ci(tmp_path)
    assert note.startswith("skipped: workflow list unreadable"), note

    # The dispatch refused after a healthy lookup is a line about refusal, not a crash.
    _wire(monkeypatch, statuses={
        "actions/workflows?per_page": (200, {"workflows": [
            {"id": 1, "name": "Mercury pairwise campaign", "state": "active"}]}),
        "status=queued": (200, {"total_count": 0}),
        "status=in_progress": (200, {"total_count": 0}),
        "dispatches": (403, {"error": "Resource not accessible by integration"}),
    })
    note = campaign_kick.maybe_kick_from_ci(tmp_path)
    assert note.startswith("refused:") and "403" in note, note

    # Trash from the network is still just a line: the real _request converts transport failures to
    # HTTP 0, and anything that escapes it is caught by the entry point rather than raised into CI.
    def explode(*a, **k):
        raise RuntimeError("socket closed")

    monkeypatch.setattr(campaign_kick, "_request", explode)
    note = campaign_kick.maybe_kick_from_ci(tmp_path)
    assert note.startswith("skipped: kick check raised RuntimeError"), note


def test_no_instruction_means_no_network_call_at_all(tmp_path: Path, monkeypatch) -> None:
    calls = _wire(monkeypatch, statuses={})
    _ci_env(monkeypatch)
    assert campaign_kick.maybe_kick_from_ci(tmp_path) == ""
    assert calls == [], "an idle repository must not be polled for a kick that was never written"


def test_one_kick_can_wake_every_stalled_campaign(tmp_path: Path, monkeypatch) -> None:
    """A missing scheduler tick is a repo-wide symptom, so the instruction may name both workflows and the
    push dispatches one leg of each; a blank name list is not an instruction at all."""
    _kick(tmp_path, workflow=["Mercury pairwise campaign", "Reasoning-Atria pairwise campaign"],
          dispatch_ref="main")
    calls = _wire(monkeypatch, statuses={
        "actions/workflows?per_page": (200, {"workflows": [
            {"id": 1, "name": "Mercury pairwise campaign", "state": "active"},
            {"id": 2, "name": "Reasoning-Atria pairwise campaign", "state": "active"}]}),
        "status=queued": (200, {"total_count": 0}),
        "status=in_progress": (200, {"total_count": 0}),
        "workflows/2/dispatches": (403, {"error": "Resource not accessible by integration"}),
    })
    _ci_env(monkeypatch)
    note = campaign_kick.maybe_kick_from_ci(tmp_path)
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 2, posts
    assert {json.loads(p[2])["ref"] for p in posts} == {"main"}, posts
    assert "dispatched:" in note and "refused:" in note, note

    for blank in ([], [""], ["  "], None, ""):
        _kick(tmp_path, workflow=blank)
        assert campaign_kick.read_kick(tmp_path) is None, blank


def test_the_cli_prints_the_verdict_and_exits_zero(tmp_path: Path, monkeypatch) -> None:
    import contextlib
    import io

    _kick(tmp_path)
    _wire(monkeypatch, statuses={
        "actions/workflows?per_page": (200, {"workflows": [
            {"id": 1, "name": "Mercury pairwise campaign", "state": "active"}]}),
        "status=queued": (200, {"total_count": 0}),
        "status=in_progress": (200, {"total_count": 1}),
    })
    _ci_env(monkeypatch)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert campaign_kick.main() == 0
    out = buf.getvalue()
    assert "::warning::campaign kick:" in out and "already queued or running" in out, out
