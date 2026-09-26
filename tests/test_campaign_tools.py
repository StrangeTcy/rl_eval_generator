"""Resilient-campaign behaviour: covering matrix, provider-outage patience,
compile-only unreferenced environments, and gate-pass carry-over on resume."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.instance_oracle_gate import REFERENCES
from tools.run_suite import run_suite
from tools.suite_inventory import build_manifest

ROOT = Path(__file__).resolve().parents[1]


def _capture_gate(monkeypatch, calls):
    def fake(manifest, **kwargs):
        calls.append(manifest)
        return {"instance_coverage_complete": True, "provider_calls": 0, "cases": []}

    monkeypatch.setattr("tools.instance_oracle_gate.validate_manifest_instances", fake)


def _episode(final, http_attempts=1, returncode=1):
    return subprocess.CompletedProcess(
        [],
        returncode,
        stdout=json.dumps(
            {"run_dir": "runs/fake", "http_attempts": http_attempts, "final": final}
        ),
        stderr="",
    )


def _provider_error_episode(http_attempts=2):
    return _episode(
        {"verdict": "FAIL", "score": 0.0, "failure_mode": "api_error"},
        http_attempts=http_attempts,
    )


def _scored_episode(http_attempts=1):
    return _episode(
        {"verdict": "PASS", "score": 1.0, "failure_mode": "pass"},
        http_attempts=http_attempts,
        returncode=0,
    )


def _manifest_with(*environments):
    manifest = build_manifest(root=ROOT, matrix="representative", seeds=[0])
    cases = [
        case for case in manifest["cases"]
        if case.get("environment") in set(environments)
    ]
    assert len(cases) == len(environments), "expected one representative case per env"
    manifest["cases"] = cases
    manifest["case_count"] = len(cases)
    # The scheduler tests replace the global subprocess with episode fakes, so
    # the oracle preflight must not generate environments in-process here.
    manifest["environments"] = []
    return manifest


def _run(tmp_path, monkeypatch, manifest, **kwargs):
    monkeypatch.setenv("CAMPAIGN_TEST_KEY", "test-secret")
    defaults = {
        "output_dir": tmp_path / "suite",
        "provider": "custom",
        "model": "offline/pinned",
        "api_key_env": "CAMPAIGN_TEST_KEY",
        "api_base": "https://example.invalid/v1",
        "max_steps": 1,
        "max_tokens": 7,
        "invalid_retries": 0,
        "max_retries": 1,
        "allow_compile_only_oracles": True,
    }
    defaults.update(kwargs)
    return run_suite(manifest, **defaults)


def test_covering_matrix_exercises_every_axis_level():
    manifest = build_manifest(root=ROOT, matrix="covering", seeds=[0])
    assert manifest["selection"]["matrix"] == "covering"
    cases_by_env: dict[str, list[dict]] = {}
    for case in manifest["cases"]:
        cases_by_env.setdefault(str(case["environment"]), []).append(case)
    for environment in manifest["environments"]:
        name = environment["environment"]
        env_cases = cases_by_env[name]
        expected = 1 + sum(
            len(axis["levels"]) - 1 for axis in environment["axes"]
        )
        assert len(env_cases) == expected, name
        axis_ids = [axis["id"] for axis in environment["axes"]]
        for axis in environment["axes"]:
            covered = set()
            for case in env_cases:
                levels = str(case["difficulty"]).split(",")
                values = dict(zip(axis_ids, levels, strict=True))
                covered.add(values[axis["id"]])
            assert covered == set(axis["levels"]), (name, axis["id"], covered)


def test_covering_matrix_is_deterministic():
    first = build_manifest(root=ROOT, matrix="covering", seeds=[0])
    second = build_manifest(root=ROOT, matrix="covering", seeds=[0])
    assert [case["case_id"] for case in first["cases"]] == [
        case["case_id"] for case in second["cases"]
    ]


def test_provider_outage_patience_retries_case_within_window(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph")
    attempts: list[subprocess.CompletedProcess] = [
        _provider_error_episode(http_attempts=2),
        _scored_episode(http_attempts=1),
    ]
    sleeps: list[float] = []
    monkeypatch.setattr("tools.run_suite._sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: attempts.pop(0),
    )
    checkpoint = _run(
        tmp_path, monkeypatch, manifest,
        provider_outage_patience_seconds=600,
        provider_outage_backoff_seconds=60,
    )
    assert checkpoint["paused"] is False
    result = checkpoint["results"][0]
    assert result["status"] == "scored"
    assert result["provider_outage_retries"] == 1
    assert result["http_attempts"] == 3
    assert sleeps == [60]
    assert checkpoint["provider_outage"]["waited_seconds"] == 60


def test_provider_outage_patience_exhaustion_pauses(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph")
    monkeypatch.setattr("tools.run_suite._sleep", lambda s: None)
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _provider_error_episode(http_attempts=2),
    )
    checkpoint = _run(
        tmp_path, monkeypatch, manifest,
        provider_outage_patience_seconds=90,
        provider_outage_backoff_seconds=60,
    )
    assert checkpoint["paused"] is True
    assert checkpoint["pause_reason"] == "provider_error"
    result = checkpoint["results"][0]
    assert result["status"] == "paused_provider_error"
    assert result["http_attempts"] == 4
    assert checkpoint["provider_outage"]["waited_seconds"] == 60
    assert checkpoint["provider_outage"]["retries"] == 1


def test_provider_outage_retry_stops_at_attempt_budget(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph")
    monkeypatch.setattr("tools.run_suite._sleep", lambda s: None)
    calls: list[list] = []
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: (
            calls.append(command),
            _provider_error_episode(http_attempts=2),
        )[1],
    )
    checkpoint = _run(
        tmp_path, monkeypatch, manifest,
        max_http_attempts=6,
        provider_outage_patience_seconds=3600,
        provider_outage_backoff_seconds=60,
    )
    assert checkpoint["paused"] is True
    assert checkpoint["pause_reason"] == "provider_error"
    assert len(calls) == 3
    result = checkpoint["results"][0]
    assert result["http_attempts"] == 6


def test_provider_outage_backoff_never_exceeds_wall_budget(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph")
    sleeps: list[float] = []
    monkeypatch.setattr("tools.run_suite._sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _provider_error_episode(http_attempts=1),
    )
    checkpoint = _run(
        tmp_path, monkeypatch, manifest,
        max_wall_seconds=5,
        provider_outage_patience_seconds=3600,
        provider_outage_backoff_seconds=60,
    )
    assert checkpoint["paused"] is True
    assert checkpoint["pause_reason"] == "provider_error"
    assert sleeps == []


def test_each_attempt_is_bounded_by_the_case_http_ceiling(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph")
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _provider_error_episode(http_attempts=999),
    )
    with pytest.raises(ValueError, match="bounded HTTP-attempt ceiling"):
        _run(
            tmp_path, monkeypatch, manifest,
            max_http_attempts=10,
            provider_outage_patience_seconds=600,
        )


def test_unreferenced_compile_only_splits_gate_and_labels_rows(tmp_path, monkeypatch):
    assert "glyph" in REFERENCES
    assert "tensor_functor" not in REFERENCES
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph", "tensor_functor")
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _scored_episode(),
    )
    checkpoint = _run(
        tmp_path, monkeypatch, manifest,
        unreferenced_compile_only=True,
    )
    assert [case["environment"] for case in gate_calls[0]["cases"]] == ["glyph"]
    guarantees = {
        row["case_id"]: row["judge_guarantee"] for row in checkpoint["results"]
    }
    assert set(guarantees.values()) == {"behavioral_reference", "compile_only"}
    assert checkpoint["instance_gate"]["gated_case_count"] == 1
    assert checkpoint["instance_gate"]["compile_only_case_count"] == 1
    report = json.loads(
        (tmp_path / "suite" / "instance_oracles.json").read_text(encoding="utf-8")
    )
    assert len(report["compile_only_cases"]) == 1
    assert "compile-only" in report["compile_only_guarantee"]


def test_unreferenced_compile_only_requires_explicit_override(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph", "tensor_functor")
    with pytest.raises(ValueError, match="requires allow-compile-only-oracles"):
        _run(
            tmp_path, monkeypatch, manifest,
            allow_compile_only_oracles=False,
            unreferenced_compile_only=True,
        )


def test_unreferenced_env_still_blocks_the_full_gate_without_the_flag(tmp_path, monkeypatch):
    # No instance-gate stub here: the real gate must refuse the unreferenced
    # environment exactly as before (the relaxation is opt-in per campaign).
    manifest = _manifest_with("tensor_functor")
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _scored_episode(),
    )
    with pytest.raises(ValueError, match="does not override this gate"):
        _run(tmp_path, monkeypatch, manifest, allow_compile_only_oracles=True)


def test_stop_after_gates_writes_carryable_checkpoint_without_episodes(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph", "tensor_functor")
    calls: list[list] = []
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: (calls.append(command), _scored_episode())[1],
    )
    checkpoint = _run(
        tmp_path, monkeypatch, manifest,
        unreferenced_compile_only=True,
        gate_context_sha="sha-stop",
        stop_after_gates=True,
    )
    assert checkpoint["provider_free_validation_complete"] is True
    assert checkpoint["paused"] is False
    assert checkpoint["results"] == []
    assert calls == []  # no episode subprocess may start in the gate phase
    assert checkpoint["instance_gate"]["gate_context_sha"] == "sha-stop"


def test_gate_pass_carries_across_resume_with_matching_context(tmp_path, monkeypatch):
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph")
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _scored_episode(),
    )
    first = _run(
        tmp_path, monkeypatch, manifest,
        unreferenced_compile_only=True,
        gate_context_sha="abc123",
    )
    assert first["paused"] is False
    assert first["instance_gate"]["gate_context_sha"] == "abc123"
    assert len(gate_calls) == 1

    def _refuse(manifest, **kwargs):
        raise AssertionError("the exact-instance gate must not re-run on a matching resume")

    monkeypatch.setattr("tools.instance_oracle_gate.validate_manifest_instances", _refuse)
    second = _run(
        tmp_path, monkeypatch, manifest,
        unreferenced_compile_only=True,
        gate_context_sha="abc123",
    )
    assert second["paused"] is False
    assert second["instance_gate"]["report"]["carried_from_checkpoint"] is True
    report = json.loads(
        (tmp_path / "suite" / "instance_oracles.json").read_text(encoding="utf-8")
    )
    assert report["carried_from_checkpoint"] is True

    # A different code context invalidates the carry and re-runs the gate.
    gate_calls.clear()
    _capture_gate(monkeypatch, gate_calls)
    third = _run(
        tmp_path, monkeypatch, manifest,
        unreferenced_compile_only=True,
        gate_context_sha="def456",
        retry_recorded=True,
    )
    assert len(gate_calls) == 1
    assert third["instance_gate"]["gate_context_sha"] == "def456"


def test_order_cases_referenced_first_puts_validated_envs_before_compile_only():
    from tools.atria_campaign import _order_cases_referenced_first

    referenced = sorted(REFERENCES)[:2]
    assert len(referenced) == 2
    input_order = ["unreferenced_env_x", referenced[0], "unreferenced_env_y",
                   referenced[1], "unreferenced_env_x"]
    cases = [{"case_id": f"{env}-1", "environment": env} for env in input_order]
    manifest = {"cases": [dict(case) for case in cases]}
    _order_cases_referenced_first(manifest)
    envs = [case["environment"] for case in manifest["cases"]]
    assert set(envs[:2]) == set(referenced)
    assert set(envs[2:]) == {"unreferenced_env_x", "unreferenced_env_y"}
    # Stable: relative order preserved inside each group.
    assert [e for e in envs if e not in referenced] == [
        e for e in input_order if e not in referenced]
    assert [e for e in envs if e in referenced] == [
        e for e in input_order if e in referenced]
    ordering = manifest["campaign_case_ordering"]
    assert ordering["policy"] == "referenced_environments_first"
    assert ordering["referenced_case_count"] == 2
    # Deterministic: same input, same output.
    again = {"cases": [dict(case) for case in cases]}
    _order_cases_referenced_first(again)
    assert [c["case_id"] for c in again["cases"]] == [c["case_id"] for c in manifest["cases"]]
