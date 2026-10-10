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


def _state(
    tmp_path: Path, *, execution_mode: str = "paid", campaign_ref: str = REF,
    provider: str = "atria",
) -> None:
    (tmp_path / "campaign_ref.txt").write_text(campaign_ref + "\n", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_intent.json",
        {
            "schema_version": 1,
            "provider": provider,
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


def test_supervisor_can_validate_a_provider_specific_state(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    assert decide_tick(tmp_path, expected_provider="atria")["mode"] == "resume"
    assert decide_tick(tmp_path, expected_provider="mercury") == {
        "mode": "none",
        "reason": "state artifact intent provider does not match expected target 'mercury'",
    }


def test_interrupted_non_checkpointed_t1_is_an_operator_stop(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid", provider="mercury")
    (tmp_path / "t1_started.json").write_text('{"phase":"started"}', encoding="utf-8")

    decision = decide_tick(tmp_path, expected_provider="mercury")

    assert decision["mode"] == "none"
    assert "no automatic provider-call replay" in decision["reason"]


def test_completed_t1_report_allows_campaign_resume(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    (tmp_path / "t1_started.json").write_text('{"phase":"started"}', encoding="utf-8")
    (tmp_path / "t1_same_fact_presentation.json").write_text("{}", encoding="utf-8")

    decision = decide_tick(tmp_path, expected_provider="atria")

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"


def test_missing_state_fails_closed_and_branch_name_dispatch_resumes_pinned(tmp_path: Path) -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    assert decide_tick(tmp_path)["mode"] == "none"

    # campaign_ref.txt holds the dispatched ref STRING (a branch name, or the
    # default "main"), while the checkpoint records the commit SHA the
    # controller executed. A mismatch must resume pinned to the checkpoint's
    # commit — the exact code that produced the state — instead of refusing:
    # a strict string comparison permanently blocks every branch-name
    # dispatch, and the advertised cron continuation never runs.
    _state(tmp_path, campaign_ref="arena/01a0ed2f-rl-eval-generator")
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
    assert "pinned to checkpoint commit" in decision["reason"]
