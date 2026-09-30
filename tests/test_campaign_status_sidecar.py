from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import campaign_status_sidecar  # noqa: E402
from tools.campaign_progress import write_progress  # noqa: E402
from tools.campaign_status_sidecar import _body, _progress_bar  # noqa: E402


@pytest.fixture(autouse=True)
def _issue_selection_is_off(monkeypatch):
    """Keep Issue selection out of every test in this file.

    Choosing an Issue consults the pin file in the checked-out ref and then the
    Issues API. These tests are about the comment lifecycle once an Issue exists,
    so both are stubbed off: it forces the create path they were written
    against, and it keeps a unit test from reaching the network. Issue selection
    has its own coverage in test_campaign_status_issue_selection.py.
    """
    monkeypatch.setattr(campaign_status_sidecar, "_pinned_issue_number", lambda: None)
    monkeypatch.setattr(
        campaign_status_sidecar, "_newest_open_status_issue", lambda *a, **k: None
    )


def test_sidecar_renders_durable_gate_progress_without_network(tmp_path: Path) -> None:
    write_progress(
        tmp_path,
        phase="exact-instance gate",
        gate_total=72,
        gate_completed=18,
        current_case="glyph__hard-data-clue",
        current_started_at="2026-09-29T00:00:00Z",
    )
    (tmp_path / "instance_oracles_partial.json").write_text(
        json.dumps({"rows": {str(index): {} for index in range(18)}}), encoding="utf-8"
    )

    body = _body(tmp_path)

    assert "exact-instance gate" in body
    assert "18 / 72" in body
    assert "**Gate progress:** `█████░░░░░░░░░░░░░░░`" in body
    assert "glyph__hard-data-clue" in body
    assert "fail-open sidecar" in body


def test_sidecar_renders_episode_checkpoint_progress_without_network(tmp_path: Path) -> None:
    write_progress(
        tmp_path,
        phase="episodes",
        episodes_total=194,
        episodes_completed=7,
        current_case="moco__queue-math-hard",
        pause_reason=None,
    )
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps({"manifest_case_count": 194, "results": [{"case_id": str(i)} for i in range(7)]}),
        encoding="utf-8",
    )

    body = _body(tmp_path)

    assert "7 / 194" in body
    assert "**Episodes progress:** `░░░░░░░░░░░░░░░░░░░░`" in body
    assert "moco__queue-math-hard" in body


def test_progress_bar_keeps_raw_count_display_separate() -> None:
    assert _progress_bar(10, 20) == "██████████░░░░░░░░░░"
    assert _progress_bar(20, 20) == "████████████████████"
    assert _progress_bar(0, 0) is None


def test_sidecar_renders_terminal_state_pause_reason_and_retries(tmp_path: Path) -> None:
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps(
            {
                "started_at": "2026-09-29T00:00:00Z",
                "paused": True,
                "pause_reason": "infrastructure_error",
                "infrastructure_retries": {"case-a": 2},
                "run": {"execution_state": "active"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "campaign_report.json").write_text(
        json.dumps({"status": "paused", "pause_reason": "infrastructure_error"}),
        encoding="utf-8",
    )

    body = _body(tmp_path)

    assert "**Campaign state:** `paused`" in body
    assert "**Pause reason:** `infrastructure_error`" in body
    assert "**Retries:** `infrastructure 2`" in body
    assert "**Campaign elapsed:**" in body


def test_sidecar_reuses_one_durable_issue_and_comment(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_api(_token, method, path, payload=None):
        calls.append((method, path))
        if method == "POST" and path.endswith("/issues"):
            return {"number": 42}
        if method == "POST":
            assert path.endswith("/issues/42/comments")
            return {"id": 99}
        assert method == "PATCH"
        assert path.endswith("/issues/comments/99")
        return {"id": 99}

    monkeypatch.setattr(campaign_status_sidecar, "_api", fake_api)

    campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token")
    campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token")

    assert calls == [
        ("POST", "/repos/owner/repository/issues"),
        ("POST", "/repos/owner/repository/issues/42/comments"),
        ("PATCH", "/repos/owner/repository/issues/comments/99"),
        ("PATCH", "/repos/owner/repository/issues/comments/99"),
    ]
    state = json.loads((tmp_path / "campaign_status_comment.json").read_text(encoding="utf-8"))
    assert state["issue_number"] == 42
    assert state["comment_id"] == 99


def test_sidecar_updates_the_existing_issue_three_status_comment(tmp_path: Path, monkeypatch) -> None:
    """The workflow's resume router stores the discovered #3 comment ID, so
    the pinned observer must update that comment instead of creating an Issue.
    """
    calls: list[tuple[str, str]] = []
    (tmp_path / "campaign_status_comment.json").write_text(
        json.dumps({"issue_number": 3, "comment_id": 303}), encoding="utf-8"
    )

    def fake_api(_token, method, path, payload=None):
        calls.append((method, path))
        assert method == "PATCH"
        assert path == "/repos/owner/repository/issues/comments/303"
        return {"id": 303}

    monkeypatch.setattr(campaign_status_sidecar, "_api", fake_api)

    assert campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token") is None

    assert calls == [("PATCH", "/repos/owner/repository/issues/comments/303")]
    state = json.loads((tmp_path / "campaign_status_comment.json").read_text(encoding="utf-8"))
    assert state["issue_number"] == 3
    assert state["comment_id"] == 303


def test_sidecar_uses_restored_issue_three_without_creating_a_new_issue(tmp_path: Path, monkeypatch) -> None:
    """A resume seed of issue_number=3 pins the pinned sidecar to the existing
    monitor. It must create/update a comment on that Issue, never POST /issues.
    """
    calls: list[tuple[str, str]] = []
    state_path = tmp_path / "campaign_status_comment.json"
    state_path.write_text(
        json.dumps({"issue_number": 3, "campaign_started_at": "2026-09-29T13:34:40Z"}),
        encoding="utf-8",
    )

    def fake_api(_token, method, path, payload=None):
        calls.append((method, path))
        if method == "POST":
            assert path == "/repos/owner/repository/issues/3/comments"
            return {"id": 303}
        assert method == "PATCH"
        assert path == "/repos/owner/repository/issues/comments/303"
        return {"id": 303}

    monkeypatch.setattr(campaign_status_sidecar, "_api", fake_api)

    campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token")
    campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token")

    assert calls == [
        ("POST", "/repos/owner/repository/issues/3/comments"),
        ("PATCH", "/repos/owner/repository/issues/comments/303"),
        ("PATCH", "/repos/owner/repository/issues/comments/303"),
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["issue_number"] == 3
    assert state["comment_id"] == 303


def test_sidecar_does_not_create_another_issue_when_comment_creation_retries(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    comment_attempts = 0

    def fake_api(_token, method, path, payload=None):
        nonlocal comment_attempts
        calls.append((method, path))
        if method == "POST" and path.endswith("/issues"):
            return {"number": 42}
        if method == "POST":
            comment_attempts += 1
            if comment_attempts == 1:
                raise campaign_status_sidecar.urllib.error.HTTPError(path, 503, "unavailable", {}, None)
            return {"id": 99}
        return {"id": 99}

    monkeypatch.setattr(campaign_status_sidecar, "_api", fake_api)

    campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token")
    campaign_status_sidecar.report_once(tmp_path, "owner/repository", "test-token")

    assert calls.count(("POST", "/repos/owner/repository/issues")) == 1
    assert calls.count(("POST", "/repos/owner/repository/issues/42/comments")) == 2


def _write_checkpoint(tmp_path: Path, checkpoint: dict) -> None:
    (tmp_path / "suite_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")


def test_body_names_the_case_holding_the_infrastructure_retry_budget(tmp_path: Path) -> None:
    _write_checkpoint(tmp_path, {
        "paused": True,
        "pause_reason": "infrastructure_error",
        "infrastructure_retries": {
            "weird_machine/hard/0": campaign_status_sidecar.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES - 1,
            "glyph/easy/0": campaign_status_sidecar.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES - 2,
        },
        "results": [{
            "case_id": "weird_machine/hard/0",
            "status": "infrastructure_error",
            "error": "arena controller or judge failed before producing a valid score",
            "stdout_tail": "SHOULD-NOT-APPEAR",
        }],
    })

    body = campaign_status_sidecar._body(tmp_path)

    assert "Infrastructure retries by case" in body
    bound = campaign_status_sidecar.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES
    assert f"`weird_machine/hard/0`: {bound - 1}/{bound} (1 automatic retry left)" in body
    assert f"`glyph/easy/0`: {bound - 2}/{bound} (2 automatic retries left)" in body
    # The sidecar reports durable metadata only, never captured process output.
    assert "SHOULD-NOT-APPEAR" not in body


def test_body_flags_an_exhausted_infrastructure_budget(tmp_path: Path) -> None:
    _write_checkpoint(tmp_path, {
        "paused": True,
        "pause_reason": "infrastructure_error_retries_exhausted",
        "infrastructure_retries": {
            "weird_machine/hard/0": campaign_status_sidecar.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1,
        },
    })

    assert "budget exhausted, stops for an operator" in campaign_status_sidecar._body(tmp_path)


def test_body_omits_the_section_without_infrastructure_retries(tmp_path: Path) -> None:
    _write_checkpoint(tmp_path, {"paused": False, "infrastructure_retries": {}})

    assert "Infrastructure retries by case" not in campaign_status_sidecar._body(tmp_path)


def _run_sidecar_once(tmp_path: Path, monkeypatch, api) -> dict:
    monkeypatch.setattr(campaign_status_sidecar, "_api", api)
    monkeypatch.setenv("GH_TOKEN", "non-secret-test-value")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repository")
    campaign_status_sidecar.main(["--out", str(tmp_path), "--once"])
    return json.loads(
        (tmp_path / campaign_status_sidecar.FINAL_HEARTBEAT).read_text(encoding="utf-8")
    )


def test_heartbeat_records_a_published_update(tmp_path: Path, monkeypatch) -> None:
    def ok(_token, method, path, payload=None):
        return {"number": 7, "id": 99}

    heartbeat = _run_sidecar_once(tmp_path, monkeypatch, ok)

    assert heartbeat["published"] == 1
    assert heartbeat["failures"] == 0
    assert heartbeat["consecutive_failures"] == 0
    assert heartbeat["last_error"] is None
    assert heartbeat["last_published_at"]
    assert isinstance(heartbeat["pid"], int)


def test_heartbeat_records_why_the_api_refused(tmp_path: Path, monkeypatch) -> None:
    def forbidden(_token, _method, path, payload=None):
        raise campaign_status_sidecar.urllib.error.HTTPError(
            path, 403, "rate limit exceeded", {}, None
        )

    heartbeat = _run_sidecar_once(tmp_path, monkeypatch, forbidden)

    # The distinction the old sidecar could not express: it ran, and was
    # refused, rather than silently dying.
    assert heartbeat["published"] == 0
    assert heartbeat["failures"] == 1
    assert heartbeat["consecutive_failures"] == 1
    assert "403" in heartbeat["last_error"]
    assert heartbeat["last_error_at"]
    assert heartbeat["updated_at"]


def test_final_heartbeat_does_not_clobber_the_periodic_record(tmp_path: Path, monkeypatch) -> None:
    periodic = {"role": "periodic", "cycles": 240, "published": 239, "failures": 1}
    campaign_status_sidecar._write_heartbeat(tmp_path, periodic)

    _run_sidecar_once(tmp_path, monkeypatch, lambda *_a, **_k: {"number": 7, "id": 99})

    preserved = json.loads(
        (tmp_path / campaign_status_sidecar.HEARTBEAT).read_text(encoding="utf-8")
    )
    assert preserved["cycles"] == 240


def test_report_once_reports_the_failure_but_still_never_raises(tmp_path: Path, monkeypatch) -> None:
    def broken(_token, _method, path, payload=None):
        raise campaign_status_sidecar.urllib.error.URLError("connection reset")

    monkeypatch.setattr(campaign_status_sidecar, "_api", broken)

    assert campaign_status_sidecar.report_once(tmp_path, "owner/repository", "t") is not None


def test_describe_error_truncates_and_names_the_type() -> None:
    long = campaign_status_sidecar._describe_error(ValueError("x" * 500))
    assert long.startswith("ValueError: ")
    assert len(long) <= 200
