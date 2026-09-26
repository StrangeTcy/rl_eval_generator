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
        rows = [
            {
                "case_id": case.get("case_id"),
                "environment": case.get("environment"),
                "status": "passed",
                "provider_calls": 0,
                "variants": [],
            }
            for case in manifest.get("cases", [])
        ]
        return {
            "schema_version": 1,
            "provider_calls": 0,
            "instance_coverage_complete": bool(rows)
            and all(row["status"] == "passed" for row in rows),
            "cases": rows,
        }

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


def test_resume_end_to_end_fake_provider_semantics(tmp_path, monkeypatch):
    """One fake-provider run demonstrating every resume guarantee:

    - completed cases are not re-run (and their rows are untouched);
    - the interrupted case is retried and scores;
    - cumulative HTTP attempts survive resume in a persistent total;
    - counters are neither reset nor double-counted;
    - metadata drift (a changed ceiling) rejects the checkpoint.
    """
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    envs = ["glyph", "epistemic_games", "categorical_lenses", "regex_state_machine"]
    manifest = _manifest_with(*envs)
    assert len(manifest["cases"]) == 4

    episode_log: list[dict] = []

    def _episode_cmd(command, **kwargs):
        # The episode command embeds the case id; record which case ran.
        cmd = " ".join(str(part) for part in command)
        episode_log.append(cmd)
        return scripted.pop(0)

    monkeypatch.setattr("tools.run_suite.subprocess.run", _episode_cmd)
    monkeypatch.setattr("tools.run_suite._sleep", lambda s: None)
    monkeypatch.setenv("CAMPAIGN_TEST_KEY", "test-secret")

    def _case_id(cmd):
        # Episode commands carry "--env <environment> --difficulty ..."; the
        # manifest under test has one representative case per environment.
        parts = cmd.split()
        return parts[parts.index("--env") + 1]

    common = dict(
        provider="custom",
        model="offline/pinned",
        api_key_env="CAMPAIGN_TEST_KEY",
        api_base="https://example.invalid/v1",
        max_steps=1,
        max_tokens=7,
        invalid_retries=0,
        max_retries=1,
        allow_compile_only_oracles=True,
        max_http_attempts=100,
    )

    # --- Dispatch 1: c1 and c2 score, c3 hits a provider outage with zero
    # patience (pauses immediately), c4 is never started.
    scripted = [
        _scored_episode(http_attempts=2),                                   # glyph PASS
        _episode({"verdict": "FAIL", "score": 0.0, "failure_mode": "fail"},
                 http_attempts=1, returncode=0),                            # epistemic FAIL
        _provider_error_episode(http_attempts=2),                           # lenses outage
    ]
    first = run_suite(
        manifest, output_dir=tmp_path / "suite",
        provider_outage_patience_seconds=0, provider_outage_backoff_seconds=60,
        **common,
    )
    assert first["paused"] is True and first["pause_reason"] == "provider_error"
    rows = {row["case_id"]: row for row in first["results"]}
    assert len(rows) == 3
    assert rows[manifest["cases"][0]["case_id"]]["status"] == "scored"
    assert rows[manifest["cases"][1]["case_id"]]["verdict"] == "FAIL"
    assert rows[manifest["cases"][2]["case_id"]]["status"] == "paused_provider_error"
    assert manifest["cases"][3]["case_id"] not in rows
    assert first["http_attempts_total"] == 5  # 2 + 1 + 2, wastage included
    # Only terminal rows must stay untouched; the paused row is expected to
    # be replaced by its retry on resume.
    first_rows = {
        cid: dict(row) for cid, row in rows.items()
        if row["status"] in {"scored", "generation_error", "compile_error",
                             "blocked_config_drift"}
    }
    assert len(first_rows) == 2

    # --- Dispatch 2: provider healthy.  Only the interrupted case and the
    # never-started case run; the two completed rows are byte-identical.
    scripted = [
        _episode({"verdict": "FAIL", "score": 0.0, "failure_mode": "fail"},
                 http_attempts=1, returncode=0),                            # lenses retry
        _scored_episode(http_attempts=2),                                   # regex PASS
    ]
    dispatch2_log_len = len(episode_log)
    second = run_suite(
        manifest, output_dir=tmp_path / "suite",
        provider_outage_patience_seconds=0, provider_outage_backoff_seconds=60,
        **common,
    )
    resumed_cmds = episode_log[dispatch2_log_len:]
    assert len(resumed_cmds) == 2, "resume must run exactly the two unfinished cases"
    resumed_ids = {_case_id(cmd) for cmd in resumed_cmds}
    assert resumed_ids == {
        manifest["cases"][2]["environment"], manifest["cases"][3]["environment"]}
    rows2 = {row["case_id"]: row for row in second["results"]}
    assert len(rows2) == 4
    for cid, saved in first_rows.items():
        assert rows2[cid] == saved, f"completed case {cid} must be untouched"
    assert rows2[manifest["cases"][2]["case_id"]]["status"] == "scored"
    assert rows2[manifest["cases"][3]["case_id"]]["status"] == "scored"
    # Cumulative attempts survive resume, are not reset, not double-counted:
    # 2 + 1 (dispatch 1) + 2 (wasted outage) + 1 + 2 (dispatch 2) = 8.
    assert second["http_attempts_total"] == 8

    # --- Dispatch 3: nothing left to do -> no episode subprocesses at all.
    before = len(episode_log)
    third = run_suite(
        manifest, output_dir=tmp_path / "suite",
        provider_outage_patience_seconds=0, provider_outage_backoff_seconds=60,
        **common,
    )
    assert len(episode_log) == before
    assert len(third["results"]) == 4
    assert third["http_attempts_total"] == 8

    # --- Dispatch 4: metadata drift (different HTTP ceiling) must refuse.
    with pytest.raises(ValueError, match="metadata mismatch"):
        run_suite(
            manifest, output_dir=tmp_path / "suite",
            provider_outage_patience_seconds=0, provider_outage_backoff_seconds=60,
            **{**common, "max_http_attempts": 8},
        )


def test_resume_carries_logical_call_and_token_reservations(tmp_path, monkeypatch):
    """The gpt-requested counter demonstration, calls and tokens dimension:
    a resume pauses at a case that would have run had the reservation been
    reset, and runs a case that would have paused had it been double-counted.
    """
    gate_calls: list[dict] = []
    _capture_gate(monkeypatch, gate_calls)
    manifest = _manifest_with("glyph", "epistemic_games", "categorical_lenses",
                              "regex_state_machine")
    monkeypatch.setattr("tools.run_suite._sleep", lambda s: None)
    monkeypatch.setenv("CAMPAIGN_TEST_KEY", "test-secret")

    common = dict(
        provider="custom",
        model="offline/pinned",
        api_key_env="CAMPAIGN_TEST_KEY",
        api_base="https://example.invalid/v1",
        max_steps=1,
        max_tokens=7,
        invalid_retries=0,
        max_retries=1,
        allow_compile_only_oracles=True,
        provider_outage_patience_seconds=0,
        provider_outage_backoff_seconds=60,
    )

    def _dispatches(output_dir, **ceilings):
        # Dispatch 1: two cases score, the third hits a provider outage.
        scripted = [_scored_episode(http_attempts=1),
                    _episode({"verdict": "FAIL", "score": 0.0,
                              "failure_mode": "fail"}, http_attempts=1,
                             returncode=0),
                    _provider_error_episode(http_attempts=1)]
        monkeypatch.setattr(
            "tools.run_suite.subprocess.run",
            lambda command, **kwargs: scripted.pop(0),
        )
        first = run_suite(manifest, output_dir=output_dir, **common, **ceilings)
        assert first["pause_reason"] == "provider_error"
        # Dispatch 2: provider healthy; only the interrupted case may run.
        scripted2 = [_scored_episode(http_attempts=1)]
        monkeypatch.setattr(
            "tools.run_suite.subprocess.run",
            lambda command, **kwargs: scripted2.pop(0),
        )
        second = run_suite(manifest, output_dir=output_dir, **common, **ceilings)
        return first, second

    # Scenario A — logical API calls: reservation of 3 carried from dispatch 1
    # lets the retry run (4 <= 4) and blocks case 4 (5 > 4).  A reset counter
    # would have run case 4; a double-counted one (6) would have blocked the
    # retry itself.
    _, a2 = _dispatches(tmp_path / "calls", max_api_calls=4)
    rows = {row["case_id"]: row for row in a2["results"]}
    assert rows[manifest["cases"][2]["case_id"]]["status"] == "scored"
    assert manifest["cases"][3]["case_id"] not in rows
    assert a2["paused"] is True and a2["pause_reason"] == "max_api_calls"

    # Scenario B — output tokens: 21 tokens carried (3 calls x 7) let the
    # retry run (28 <= 28) and block case 4 (35 > 28) on the token ceiling.
    _, b2 = _dispatches(tmp_path / "tokens", max_tokens_total=28)
    rows_b = {row["case_id"]: row for row in b2["results"]}
    assert rows_b[manifest["cases"][2]["case_id"]]["status"] == "scored"
    assert manifest["cases"][3]["case_id"] not in rows_b
    assert b2["paused"] is True and b2["pause_reason"] == "max_tokens_total"


def test_gate_accumulates_per_case_and_survives_mid_gate_death(tmp_path, monkeypatch):
    """The gate phase costs more CPU-hours than one runner job (Glyph/MoCo
    reference training), so it must accumulate per case: a dispatch killed
    mid-gate keeps its completed rows, and the resume revalidates only the
    missing cases."""
    assert "glyph" in REFERENCES and "regex_state_machine" in REFERENCES
    manifest = _manifest_with("glyph", "regex_state_machine")

    def _row(case):
        return {
            "case_id": case["case_id"],
            "environment": case["environment"],
            "status": "passed",
            "provider_calls": 0,
            "variants": [],
        }

    # Dispatch 1: the gate completes the first case, then the job "dies"
    # (runner timeout / kill) while validating the second.
    dying_calls: list[str] = []

    def _gate_dying(manifest, **kwargs):
        case = manifest["cases"][0]
        if dying_calls:
            raise RuntimeError("simulated runner death mid-gate")
        dying_calls.append(str(case["case_id"]))
        return {
            "schema_version": 1, "provider_calls": 0,
            "instance_coverage_complete": True, "cases": [_row(case)],
        }

    monkeypatch.setattr(
        "tools.instance_oracle_gate.validate_manifest_instances", _gate_dying)
    with pytest.raises(RuntimeError, match="simulated runner death"):
        _run(tmp_path, monkeypatch, manifest,
              unreferenced_compile_only=True, gate_context_sha="ctx-1")
    partial = json.loads(
        (tmp_path / "suite" / "instance_oracles_partial.json").read_text("utf-8"))
    assert len(partial["rows"]) == 1
    assert partial["gate_context_sha"] == "ctx-1"
    assert partial["gated_manifest_sha256"]

    # Dispatch 2 (resume): healthy gate; only the missing case may revalidate.
    resumed_calls: list[list[str]] = []

    def _gate_healthy(manifest, **kwargs):
        resumed_calls.append([str(c["case_id"]) for c in manifest["cases"]])
        return {
            "schema_version": 1, "provider_calls": 0,
            "instance_coverage_complete": True,
            "cases": [_row(c) for c in manifest["cases"]],
        }

    monkeypatch.setattr(
        "tools.instance_oracle_gate.validate_manifest_instances", _gate_healthy)
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _scored_episode(),
    )
    second = _run(tmp_path, monkeypatch, manifest,
                  unreferenced_compile_only=True, gate_context_sha="ctx-1")
    assert second["paused"] is False
    assert len(resumed_calls) == 1  # exactly one case revalidated
    assert resumed_calls[0] == [manifest["cases"][1]["case_id"]]
    assert second["instance_gate"]["report"]["gate_rows_reused_from_partial"] == 1
    assert second["instance_gate"]["gated_case_count"] == 2
    report = json.loads(
        (tmp_path / "suite" / "instance_oracles.json").read_text("utf-8"))
    assert report["gate_rows_reused_from_partial"] == 1
    assert len(report["cases"]) == 2
    assert {row["environment"] for row in report["cases"]} == {
        "glyph", "regex_state_machine"}
    # The episodes ran for both cases after the gate completed.
    assert len(second["results"]) == 2
    assert all(row["status"] == "scored" for row in second["results"])


def test_partial_gate_rows_require_matching_context(tmp_path, monkeypatch):
    """A partial gate recorded under a different deployed-code context is
    rejected wholesale: every case revalidates under the new context."""
    assert "glyph" in REFERENCES and "regex_state_machine" in REFERENCES
    manifest = _manifest_with("glyph", "regex_state_machine")

    def _row(case):
        return {
            "case_id": case["case_id"],
            "environment": case["environment"],
            "status": "passed",
            "provider_calls": 0,
            "variants": [],
        }

    dying_calls: list[str] = []

    def _gate_dying(manifest, **kwargs):
        case = manifest["cases"][0]
        if dying_calls:
            raise RuntimeError("simulated runner death mid-gate")
        dying_calls.append(str(case["case_id"]))
        return {
            "schema_version": 1, "provider_calls": 0,
            "instance_coverage_complete": True, "cases": [_row(case)],
        }

    monkeypatch.setattr(
        "tools.instance_oracle_gate.validate_manifest_instances", _gate_dying)
    with pytest.raises(RuntimeError, match="simulated runner death"):
        _run(tmp_path, monkeypatch, manifest,
              unreferenced_compile_only=True, gate_context_sha="ctx-old")

    fresh_calls: list[list[str]] = []

    def _gate_healthy(manifest, **kwargs):
        fresh_calls.append([str(c["case_id"]) for c in manifest["cases"]])
        return {
            "schema_version": 1, "provider_calls": 0,
            "instance_coverage_complete": True,
            "cases": [_row(c) for c in manifest["cases"]],
        }

    monkeypatch.setattr(
        "tools.instance_oracle_gate.validate_manifest_instances", _gate_healthy)
    monkeypatch.setattr(
        "tools.run_suite.subprocess.run",
        lambda command, **kwargs: _scored_episode(),
    )
    second = _run(tmp_path, monkeypatch, manifest,
                  unreferenced_compile_only=True, gate_context_sha="ctx-new")
    assert sorted(
        case_id for call in fresh_calls for case_id in call
    ) == sorted(str(c["case_id"]) for c in manifest["cases"])  # all revalidated
    assert second["instance_gate"]["report"]["gate_rows_reused_from_partial"] == 0
    assert second["instance_gate"]["gate_context_sha"] == "ctx-new"
