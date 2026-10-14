"""Exhaustive persistence-boundary proof for the 194-case campaign scheduler.

This test deliberately uses the real ``run_suite`` episode loop, checkpoint
format, atomic writer, artifact ZIP transfer, and supervisor.  Only the paid
HTTP/Docker episode itself is replaced with a deterministic scored process: the
property under test is continuation after the worker disappears, not model
quality.  It injects one abrupt worker death after each of the 194 individual
result checkpoints and requires a fresh restored job to reach all 194 rows.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_suite
from tools.campaign_supervisor import decide_tick


REF = "b" * 40
CASE_COUNT = 194


class SimulatedWorkerDeath(BaseException):
    """A runner disappearance after its atomic checkpoint is durable."""


def _manifest() -> dict:
    cases = [
        {
            "case_id": f"case-{index:03d}",
            "environment": "epistemic_games",
            "difficulty": "report,ambiguous,paired,balanced,bare_table",
            "seed": 0,
        }
        for index in range(CASE_COUNT)
    ]
    return {
        "ready_for_scheduler": True,
        "case_count": CASE_COUNT,
        "repository": {"commit": REF},
        "selection": {"matrix": "covering"},
        "cases": cases,
    }


def _install_provider_free_gate_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    # The exact-instance implementation is separately tested against its real
    # environments. This proof isolates the controller's complete 194-case
    # persistence/recovery property while preserving its gate/checkpoint API.
    from tools import instance_oracle_gate, oracle_preflight

    monkeypatch.setattr(
        oracle_preflight,
        "validate_manifest_oracles",
        lambda *_args, **_kwargs: {
            "model_sweep_allowed": True,
            "api_calls": 0,
            "failure_count": 0,
            "behavioral_coverage_complete": True,
        },
    )

    def gate(manifest: dict, **_kwargs: object) -> dict:
        return {
            "schema_version": 1,
            "provider_calls": 0,
            "instance_coverage_complete": True,
            "missing_references": [],
            "cases": [
                {"case_id": case["case_id"], "status": "passed", "variants": []}
                for case in manifest["cases"]
            ],
        }

    monkeypatch.setattr(instance_oracle_gate, "validate_manifest_instances", gate)


def _install_scored_episode(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "final": {"verdict": "PASS", "score": 1.0, "failure_mode": "pass"},
            "http_attempts": 1,
            "run_dir": "deterministic-test-episode",
        }
    )
    monkeypatch.setattr(
        run_suite.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=payload, stderr=""),
    )


def _kwargs(output: Path) -> dict:
    return {
        "output_dir": output,
        "provider": "atria",
        "model": "Atria-Dawn-Preview",
        "api_key_env": "ATRIA_API_KEY",
        "api_base": "https://api.atria-asi.ai/v1",
        "sandbox": "docker",
        "max_steps": 1,
        "max_tokens": 8,
        "invalid_retries": 0,
        "max_retries": 0,
        "max_http_attempts": CASE_COUNT,
        "max_api_calls": CASE_COUNT,
        "max_tokens_total": CASE_COUNT * 8,
        "min_interval_seconds": 0,
        "provider_min_interval_seconds": 0,
        "floor_effect_after": None,
        "checkpoint_path": output / "suite_checkpoint.json",
        "allow_compile_only_oracles": True,
        "unreferenced_compile_only": True,
        "gate_context_sha": REF,
    }


def _artifact_round_trip(source: Path, destination: Path) -> None:
    archive = shutil.make_archive(str(destination) + "-artifact", "zip", root_dir=source)
    destination.mkdir()
    shutil.unpack_archive(archive, destination)


def test_every_atomic_194_case_checkpoint_recovers_to_the_only_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    monkeypatch.setenv("ATRIA_API_KEY", "non-secret-test-value")
    _install_provider_free_gate_stubs(monkeypatch)
    _install_scored_episode(monkeypatch)

    # Create a real carried gate checkpoint once, then duplicate precisely the
    # state a workflow artifact would contain before every injected death.
    gate_state = tmp_path / "gated"
    run_suite.run_suite(manifest, stop_after_gates=True, **_kwargs(gate_state))

    original_write = run_suite._write_json_atomic
    for crash_after in range(1, CASE_COUNT + 1):
        job = tmp_path / f"job-{crash_after}"
        shutil.copytree(gate_state, job)
        (job / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
        (job / "campaign_intent.json").write_text(
            json.dumps({"provider": "atria", "execution_mode": "paid"}), encoding="utf-8"
        )
        fired = False

        def crash_after_durable_result(path: Path, value: dict) -> None:
            nonlocal fired
            original_write(path, value)
            if (
                not fired
                and path.name == "suite_checkpoint.json"
                and len(value.get("results") or []) == crash_after
                and (value.get("run") or {}).get("active_case_id") is None
            ):
                fired = True
                raise SimulatedWorkerDeath(f"worker died after case {crash_after}")

        with monkeypatch.context() as isolated:
            isolated.setattr(run_suite, "_write_json_atomic", crash_after_durable_result)
            with pytest.raises(SimulatedWorkerDeath):
                run_suite.run_suite(manifest, **_kwargs(job))
        assert fired

        # This is the artifact boundary used by the workflow: no in-memory
        # state, monkeypatch object, or live process is carried into recovery.
        restored = tmp_path / f"restored-{crash_after}"
        _artifact_round_trip(job, restored)
        decision = decide_tick(restored)
        assert decision["mode"] == "resume"
        assert decision["execution_mode"] == "paid"
        assert decision["ref"] == REF

        final = run_suite.run_suite(manifest, **_kwargs(restored))
        rows = final["results"]
        assert final["paused"] is False
        assert final["run"]["execution_state"] == "completed"
        assert len(rows) == CASE_COUNT
        assert {row["case_id"] for row in rows} == {case["case_id"] for case in manifest["cases"]}
        assert {row["status"] for row in rows} == {"scored"}
        assert decide_tick(restored)["mode"] == "none"


def test_wall_reserve_pauses_before_starting_an_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A near-deadline dispatch must not spend a retry on an ordinary wall stop."""
    manifest = _manifest()
    monkeypatch.setenv("ATRIA_API_KEY", "non-secret-test-value")
    _install_provider_free_gate_stubs(monkeypatch)
    monkeypatch.setattr(run_suite, "EPISODE_EXECUTION_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(run_suite, "EPISODE_CHECKPOINT_RESERVE_SECONDS", 1)
    output = tmp_path / "wall-reserve"
    run_suite.run_suite(manifest, stop_after_gates=True, **_kwargs(output))
    monkeypatch.setattr(
        run_suite.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("the wall guard must run before subprocess launch"),
    )

    checkpoint = run_suite.run_suite(manifest, max_wall_seconds=5.9, **_kwargs(output))

    assert checkpoint["paused"] is True
    assert checkpoint["pause_reason"] == "max_wall_seconds"
    assert checkpoint["results"] == []
    assert checkpoint.get("infrastructure_retries") in (None, {})
    assert checkpoint.get("http_attempts_total", 0) == 0
    assert checkpoint["wall_limited_episode"]["case_id"] == "case-000"
    persisted = json.loads((output / "suite_checkpoint.json").read_text(encoding="utf-8"))
    assert persisted["pause_reason"] == "max_wall_seconds"
    (output / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    (output / "campaign_intent.json").write_text(
        json.dumps({"provider": "atria", "execution_mode": "paid"}), encoding="utf-8"
    )
    persisted["updated_at"] = "2020-01-01T00:00:00Z"
    (output / "suite_checkpoint.json").write_text(json.dumps(persisted), encoding="utf-8")
    assert decide_tick(output)["mode"] == "resume"


def test_independent_episode_timeout_is_a_bounded_infrastructure_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the independent per-episode timeout enters the retry ledger."""
    manifest = _manifest()
    monkeypatch.setenv("ATRIA_API_KEY", "non-secret-test-value")
    _install_provider_free_gate_stubs(monkeypatch)
    monkeypatch.setattr(run_suite, "EPISODE_EXECUTION_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(run_suite, "EPISODE_CHECKPOINT_RESERVE_SECONDS", 1)
    output = tmp_path / "episode-timeout"
    run_suite.run_suite(manifest, stop_after_gates=True, **_kwargs(output))

    def timed_out(command, **kwargs):
        raise run_suite.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(run_suite.subprocess, "run", timed_out)
    checkpoint = run_suite.run_suite(manifest, max_wall_seconds=60, **_kwargs(output))

    row = checkpoint["results"][0]
    assert checkpoint["pause_reason"] == "infrastructure_error"
    assert checkpoint["infrastructure_retries"]["case-000"] == 1
    assert row["http_attempts"] is None
    assert row["http_attempts_upper_bound_reserved"] == 1
    assert checkpoint["http_attempts_total"] == 0
    # Two now, not one: the leg no longer stops at the first unscored case, so case-001 was reached
    # and its timeout is also an unbounded attempt. The second failure in one leg is the systemic
    # condition that still ends it, and that is why this leg pauses.
    assert checkpoint["http_attempts_unknown_upper_bound_total"] == 2


def test_container_failure_is_automatically_retried_then_stops_at_its_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest()
    monkeypatch.setenv("ATRIA_API_KEY", "non-secret-test-value")
    _install_provider_free_gate_stubs(monkeypatch)
    monkeypatch.setattr(
        run_suite.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="container died"),
    )
    output = tmp_path / "container-failure"
    run_suite.run_suite(manifest, stop_after_gates=True, **_kwargs(output))
    (output / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    (output / "campaign_intent.json").write_text(
        json.dumps({"provider": "atria", "execution_mode": "paid"}), encoding="utf-8"
    )

    for attempt in range(1, run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1):
        checkpoint = run_suite.run_suite(manifest, **_kwargs(output))
        assert checkpoint["pause_reason"] == "infrastructure_error"
        assert checkpoint["infrastructure_retries"]["case-000"] == attempt
        # Cron runs on a 30-minute cadence; bypass the intentional 20-minute
        # retry backoff in this fast proof without changing production policy.
        checkpoint["updated_at"] = "2020-01-01T00:00:00Z"
        (output / "suite_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
        assert decide_tick(output)["mode"] == "resume"

    # The bound closes *the case*; it does not end the campaign. Every case fails identically here,
    # which is also the systemic condition, so the leg stops on its second failure - but no leg any
    # more reaches a non-resumable `infrastructure_error_retries_exhausted` that strands 51 unrun
    # cases behind one poisoned one.
    checkpoint = run_suite.run_suite(manifest, **_kwargs(output))
    assert checkpoint["pause_reason"] == "infrastructure_error"
    assert checkpoint["infrastructure_retries"]["case-000"] == (
        run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1
    )
    assert checkpoint["results"][0]["status"] == "infrastructure_unscored"
    assert checkpoint["results"][0]["unscored_after_attempts"] == (
        run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1
    )
    assert "did not return a scored result" in str(checkpoint["results"][0]["error"])
    assert checkpoint["unscored_cases"]["case-000"]["attempts"] == (
        run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1
    )
    # The intentional 20-minute infrastructure backoff would otherwise make `decide_tick` answer
    # `none` for a leg that simply finished a second ago, which is a fixture clock, not a policy.
    checkpoint["updated_at"] = "2020-01-01T00:00:00Z"
    (output / "suite_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    assert decide_tick(output)["mode"] == "resume"
    persisted = json.loads((output / "suite_checkpoint.json").read_text(encoding="utf-8"))
    assert persisted["results"][0]["status"] == "infrastructure_unscored"
    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))
    # Two here, because every case in this proof fails its judge identically and both had run out.
    # Counted as unscored, never as a score: the row is a harness outcome with a reason, not a zero,
    # and the cases that were never reached are still `infrastructure_error` - pending, not closed.
    assert coverage["counts"].get("infrastructure_unscored") == 2
    assert coverage["counts"].get("infrastructure_error") == 2
    assert coverage["counts"].get("scored", 0) == 0


def test_one_poisoned_case_cannot_hold_the_rest_of_the_plan_hostage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case that fails its judge while every other case scores is no longer a stop sign.

    Measured on 2026-10-13: Mercury run 35 paused at 365/416 on
    `epistemic_silence__observation=message_protocol=pair_prior=skewed_scenario=expedition__seed-0`,
    whose arena judge returned `not_submitted`, and the ten-attempt per-case bound turned that one
    case into `infrastructure_error_retries_exhausted` - non-resumable, with 51 cases never
    attempted. The plan here is six cases, one of which always fails its judge: the campaign spends
    its ten attempts, closes that case as explicitly unscored, and completes the other five.
    """
    manifest = _manifest()
    plan = 6
    manifest["cases"] = manifest["cases"][:plan]
    manifest["case_count"] = plan
    monkeypatch.setenv("ATRIA_API_KEY", "non-secret-test-value")
    _install_provider_free_gate_stubs(monkeypatch)
    poisoned = manifest["cases"][0]["case_id"]
    scored = json.dumps(
        {
            "final": {"verdict": "PASS", "score": 1.0, "failure_mode": "pass"},
            "http_attempts": 1,
            "run_dir": "deterministic-test-episode",
        }
    )

    def episode(command, **_kwargs):
        # The real command line carries `--case-id`, so exactly one case dies in the judge.
        joined = " ".join(str(part) for part in command)
        if poisoned in joined:
            return SimpleNamespace(returncode=1, stdout="", stderr="container died")
        return SimpleNamespace(returncode=0, stdout=scored, stderr="")

    output = tmp_path / "one-poisoned-case"
    monkeypatch.setattr(run_suite.subprocess, "run", episode)
    run_suite.run_suite(manifest, stop_after_gates=True, **_kwargs(output))
    (output / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    (output / "campaign_intent.json").write_text(
        json.dumps({"provider": "atria", "execution_mode": "paid"}), encoding="utf-8"
    )
    kwargs = _kwargs(output)

    for attempt in range(1, run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1):
        checkpoint = run_suite.run_suite(manifest, **kwargs)
        assert checkpoint["pause_reason"] == "infrastructure_error", attempt
        assert len(checkpoint["results"]) == plan, attempt  # the other five are already banked
        assert checkpoint["infrastructure_retries"][poisoned] == attempt
        checkpoint["updated_at"] = "2020-01-01T00:00:00Z"
        (output / "suite_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
        assert decide_tick(output)["mode"] == "resume", attempt

    final = run_suite.run_suite(manifest, **kwargs)
    rows = {row["case_id"]: row for row in final["results"]}
    assert len(rows) == plan
    assert rows[poisoned]["status"] == "infrastructure_unscored"
    assert rows[poisoned]["unscored_after_attempts"] == (
        run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1
    )
    assert sum(row["status"] == "scored" for row in rows.values()) == plan - 1
    assert final.get("paused") is not True  # nothing is left to retry, so the campaign completes
    assert final.get("pause_reason") != "infrastructure_error_retries_exhausted"
    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["counts"].get("infrastructure_unscored") == 1
    assert coverage["counts"].get("scored") == plan - 1

    # A closed case stays closed: another leg neither re-bills it nor hands it a score.
    again = run_suite.run_suite(manifest, **kwargs)
    again_rows = {row["case_id"]: row for row in again["results"]}
    assert again_rows[poisoned]["status"] == "infrastructure_unscored"
    assert again["infrastructure_retries"][poisoned] == (
        run_suite.MAX_AUTOMATIC_INFRASTRUCTURE_RETRIES + 1
    )
