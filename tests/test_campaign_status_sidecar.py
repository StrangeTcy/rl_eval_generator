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


def _probe_state(
    tmp_path: Path,
    *,
    probe: dict,
    pause_reason: str,
    episodes_completed: int = 170,
    episodes_total: int = 416,
    waited: float = 3300.0,
) -> None:
    """The durable files a leg leaves when the paid READY probe is what stopped it.

    Shaped like the Reasoning-Atria pairwise state of 2026-10-15: the progress file
    frozen at the gate write that precedes the probe, the episodes banked by earlier
    legs, and the probe's own record beside them.
    """
    write_progress(
        tmp_path,
        phase="exact-instance gate",
        gate_total=189,
        gate_completed=189,
        episodes_total=episodes_total,
        episodes_completed=episodes_completed,
        current_case=None,
    )
    (tmp_path / "compatibility.json").write_text(json.dumps(probe), encoding="utf-8")
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps(
            {
                "manifest_case_count": episodes_total,
                "paused": True,
                "pause_reason": pause_reason,
                "results": [{"case_id": str(index)} for index in range(episodes_completed)],
                "run": {"compatibility": {"status": probe.get("status"),
                                          "error_type": probe.get("error_type"),
                                          "waited_seconds": waited}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "campaign_report.json").write_text(
        json.dumps(
            {
                "status": "paused",
                "pause_reason": pause_reason,
                "resumable": pause_reason == "provider_infrastructure_error_compatibility",
                "compatibility": {"status": probe.get("status"),
                                  "attempts": probe.get("attempts"),
                                  "waited_seconds": waited},
            }
        ),
        encoding="utf-8",
    )


def test_body_names_the_probe_a_leg_is_waiting_out_instead_of_freezing_at_the_gate(tmp_path: Path) -> None:
    """The stall that reads as a stuck counter is a phase the comment never named.

    Three legs (04:52, 05:58, 06:59Z on 2026-10-15) each spent the profile's 3600 s
    outage patience inside `_compatibility_with_patience`, exited 7 and banked no row,
    while the comment kept reporting the gate snapshot the probe path never updates -
    `Episodes checkpointed: 170 / 416` with an `Updated` stamp that did not move. The
    probe's own record says which phase the leg is in, how the provider refused, and
    when it last refused; the age of that file is the liveness channel the frozen
    `Updated` line cannot be.
    """
    _probe_state(
        tmp_path,
        probe={
            "status": "failed",
            "error_type": "provider_transient",
            "status_code": None,
            "attempts": 6,
            "attempt_logs": [
                {"attempt": 5, "error_type": "http_error", "status_code": 503, "elapsed_ms": 812},
                {"attempt": 6, "error_type": "timeout", "status_code": None, "elapsed_ms": 120000},
            ],
            "diagnostic_body": "PAYLOAD-THAT-MUST-NOT-BE-RENDERED",
            "effective_request": {"model": "Atria-Dawn-Preview",
                                  "request_extra": "PAYLOAD-THAT-MUST-NOT-BE-RENDERED"},
        },
        pause_reason="provider_infrastructure_error_compatibility",
    )

    body = _body(tmp_path)

    assert "**Compatibility probe:**" in body
    probe_line = next(line for line in body.splitlines() if line.startswith("- **Compatibility probe:**"))
    assert "failed" in probe_line
    assert "provider_transient" in probe_line
    assert "last attempt timeout" in probe_line
    assert "6 attempts" in probe_line
    assert "last attempt took 120000 ms" in probe_line
    assert "written " in probe_line and " s before this comment" in probe_line
    assert "**Provider outage wait:** `3300.0 s waited" in body
    assert "**Episodes this leg:** `none" in body
    assert "Phase 2" in body and "Phase 3" in body
    # The frozen counters are still reported, unchanged and unexplained-away.
    assert "**Episodes checkpointed:** `170 / 416`" in body
    # A provider payload is never a status line.
    assert "PAYLOAD-THAT-MUST-NOT-BE-RENDERED" not in body


def test_body_reports_the_answer_shape_when_the_probe_completed_but_was_not_ready(tmp_path: Path) -> None:
    """A substantive probe failure is terminal, so its diagnosis has to be readable.

    `completion_compatibility_failed` is not resumable and the supervisor will not
    re-arm it: the provider answered, just not the exact acknowledgement the pinned
    contract asks for. Whether it was truncated or padded is the whole question, and
    the answer's shape - finish_reason and two lengths - answers it without printing
    a provider response body.
    """
    _probe_state(
        tmp_path,
        probe={
            "status": "failed",
            "error_type": "invalid_compatibility_completion",
            "status_code": 200,
            "attempts": 1,
            "attempt_logs": [],
            "finish_reason": "length",
            "content_length": 17,
            "reasoning_content_length": 8192,
            "diagnostic_body": "READY, but only after PAYLOAD-THAT-MUST-NOT-BE-RENDERED",
        },
        pause_reason="completion_compatibility_failed",
        waited=0.0,
    )

    body = _body(tmp_path)

    probe_line = next(line for line in body.splitlines() if line.startswith("- **Compatibility probe:**"))
    assert "invalid_compatibility_completion" in probe_line
    assert "HTTP 200" in probe_line
    assert "finish_reason=length" in probe_line
    assert "answer length=17" in probe_line
    assert "reasoning length=8192" in probe_line
    assert "PAYLOAD-THAT-MUST-NOT-BE-RENDERED" not in body


def test_body_stays_quiet_about_a_probe_that_passed(tmp_path: Path) -> None:
    """A passing probe is not news, and a stale pass must not be rendered as this leg's."""
    write_progress(tmp_path, phase="episodes", episodes_total=416, episodes_completed=171)
    (tmp_path / "compatibility.json").write_text(
        json.dumps({"status": "passed", "attempts": 1, "attempt_logs": []}), encoding="utf-8"
    )
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps({"manifest_case_count": 416, "results": [{"case_id": str(i)} for i in range(171)]}),
        encoding="utf-8",
    )

    body = _body(tmp_path)

    assert "**Compatibility probe:**" not in body
    assert "**Episodes this leg:**" not in body


def test_body_says_when_the_newest_probe_passed_under_an_older_legs_pause(tmp_path: Path) -> None:
    """The report is written when a leg ENDS, so its pause can be older than the probe."""
    _probe_state(
        tmp_path,
        probe={"status": "passed", "attempts": 2, "attempt_logs": []},
        pause_reason="provider_infrastructure_error_compatibility",
    )

    body = _body(tmp_path)

    assert "**Compatibility probe:** `passed" in body
    assert "the newest probe passed, so the pause above belongs to an earlier leg" in body
    assert "**Episodes this leg:** `none" not in body


def _stale_progress(tmp_path: Path) -> None:
    """Leave a checkpoint whose own timestamp is hours old, as a paused leg does."""
    write_progress(tmp_path, phase="episodes", current_case="case__office")
    progress_file = tmp_path / "campaign_progress.json"
    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    progress["updated_at"] = "2026-10-15T05:00:05Z"
    progress_file.write_text(json.dumps(progress), encoding="utf-8")


def test_the_comment_names_the_render_that_wrote_it(tmp_path: Path, monkeypatch) -> None:
    """A frozen `Updated` must read as "nothing banked", never as "reporter dead".

    `Updated` is the checkpoint's own timestamp, so a leg that pauses in Phase 2
    leaves it where it was for hours. The render line carries this comment's own
    clock, which is the only evidence in the comment that a reporter ran at all.
    """
    from datetime import UTC, datetime

    monkeypatch.setenv("GITHUB_RUN_ID", "38758437040")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    _stale_progress(tmp_path)

    body = _body(tmp_path)

    assert "- **Updated:** 2026-10-15T05:00:05Z" in body
    rendered = next(
        line for line in body.splitlines() if line.startswith("- **Comment rendered:**")
    )
    stamp = rendered.split("**Comment rendered:**", 1)[1].strip().split(", rendered by")[0]
    age = abs((datetime.now(UTC) - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds())
    assert age < 120, f"the render line must carry this comment's clock, not the checkpoint's: {stamp}"
    assert "2026-10-15T05:00:05Z" not in rendered


def test_the_render_line_names_the_leg_that_rendered_it(tmp_path: Path, monkeypatch) -> None:
    """Name the leg, so a reader can tell a chained leg from a dispatched one."""
    monkeypatch.setenv("GITHUB_RUN_ID", "38758437040")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    _stale_progress(tmp_path)

    body = _body(tmp_path)

    assert "leg run 38758437040 attempt 3" in body


def test_the_render_line_survives_a_bare_environment(tmp_path: Path, monkeypatch) -> None:
    """The sidecar is fail-open: a missing variable omits a clause, never raises."""
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    _stale_progress(tmp_path)

    body = _body(tmp_path)

    rendered = next(
        line for line in body.splitlines() if line.startswith("- **Comment rendered:**")
    )
    assert rendered.endswith("Z"), rendered
    assert "leg run" not in rendered
