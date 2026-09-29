from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import campaign_status_sidecar  # noqa: E402
from tools.campaign_progress import write_progress  # noqa: E402
from tools.campaign_status_sidecar import _body  # noqa: E402


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
    assert "moco__queue-math-hard" in body


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
