from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.campaign_supervisor import decide_tick


REF = "f" * 40


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _state(tmp_path: Path, *, execution_mode: str = "paid") -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_intent.json",
        {
            "schema_version": 1,
            "provider": "atria",
            "execution_mode": execution_mode,
            "case_manifest_sha256": "a" * 64,
            "gate_context_sha": REF,
        },
    )


def _old_timestamp() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def test_setup_bootstrap_state_resumes_after_pre_controller_failure(tmp_path: Path) -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_bootstrap.json",
        {"provider": "atria", "execution_mode": "paid"},
    )

    decision = decide_tick(tmp_path)

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == REF


def test_gate_wall_pause_resumes_without_a_suite_checkpoint(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    (tmp_path / "instance_oracles_partial.json").write_text("{}", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_report.json",
        {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True},
    )

    assert decide_tick(tmp_path) == {
        "mode": "resume",
        "execution_mode": "paid",
        "ref": REF,
        "reason": "resuming provider-free gate after an interrupted partial row",
    }


def test_gate_only_intent_resumes_the_same_provider_free_mode(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="gates_only")
    (tmp_path / "instance_oracles_partial.json").write_text("{}", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_report.json",
        {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True},
    )

    decision = decide_tick(tmp_path)

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "gates_only"
    assert decision["ref"] == REF


def test_episode_wall_pause_resumes_only_the_pinned_intended_mode(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "max_wall_seconds",
            "updated_at": _old_timestamp(),
            "run": {"manifest_commit": REF},
        },
    )

    decision = decide_tick(tmp_path)

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == REF
    assert decision["reason"] == "resuming after max_wall_seconds"


def test_bounded_container_failure_pause_resumes_but_exhaustion_does_not(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "infrastructure_error",
            "updated_at": _old_timestamp(),
            "infrastructure_retries": {"case-10": 1},
            "run": {"manifest_commit": REF},
        },
    )
    assert decide_tick(tmp_path)["mode"] == "resume"

    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "infrastructure_error_retries_exhausted",
            "updated_at": _old_timestamp(),
            "infrastructure_retries": {"case-10": 4},
            "run": {"manifest_commit": REF},
        },
    )
    assert decide_tick(tmp_path)["mode"] == "none"


def test_interrupted_active_episode_worker_resumes_without_manual_restart(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": False,
            "results": [{"case_id": "case-0", "status": "scored"}],
            "run": {
                "manifest_commit": REF,
                "execution_state": "active",
                "active_case_id": "case-1",
            },
        },
    )

    assert decide_tick(tmp_path) == {
        "mode": "resume",
        "execution_mode": "paid",
        "ref": REF,
        "reason": "resuming after an interrupted active worker",
    }


def test_completed_or_terminal_state_never_restarts_on_schedule(tmp_path: Path) -> None:
    _state(tmp_path)
    _write_json(tmp_path / "campaign_report.json", {"status": "gate_passed"})
    assert decide_tick(tmp_path)["mode"] == "none"

    _write_json(tmp_path / "campaign_report.json", {"status": "paused", "pause_reason": "max_wall_seconds"})
    _write_json(tmp_path / "wrapper_failed.json", {"pause_reason": "generation_preflight_failed"})
    assert decide_tick(tmp_path)["mode"] == "none"


def test_missing_or_mixed_continuation_state_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    assert decide_tick(tmp_path)["mode"] == "none"

    _state(tmp_path)
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "max_wall_seconds",
            "updated_at": _old_timestamp(),
            "run": {"manifest_commit": "e" * 40},
        },
    )
    assert "disagrees" in decide_tick(tmp_path)["reason"]
