"""Fail-closed provider-free exact-instance oracle integration tests."""
from __future__ import annotations

import json

import pytest

from arena.episode import EpisodeOptions, run_episode
from tools import instance_oracle_gate as gate

CSS_CASE = {"case_id": "css-easy-0", "environment": "css_state_machine",
            "difficulty": "easy,easy", "seed": 0}


def test_missing_reference_prevents_generation_or_paid_request(monkeypatch, tmp_path):
    monkeypatch.setattr(gate.env_runner, "reset", lambda *_args: pytest.fail("must not generate"))
    row = gate.validate_case({"case_id": "unconfigured", "environment": "fake_environment",
                              "difficulty": "easy", "seed": 0})
    assert row["status"] == "blocked"
    assert row["reason"] == "reference_not_configured"
    assert row["provider_calls"] == 0

    def no_credentials(*_args, **_kwargs):
        pytest.fail("must block before touching provider credentials")

    monkeypatch.setattr("arena.episode.resolve_credentials", no_credentials)
    with pytest.raises(ValueError, match="Exact-instance judge oracle failed"):
        run_episode(EpisodeOptions(provider="custom", model="offline/model", env="fake_environment",
                                   difficulty="easy", out=tmp_path / "runs"))
    reports = list((tmp_path / "runs" / "_instance_oracles").glob("*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["reason"] == "reference_not_configured"


def test_missing_suite_references_are_reported_without_slow_judge(monkeypatch):
    monkeypatch.setattr(gate, "_run_variant", lambda *_args, **_kwargs: pytest.fail("must not run"))
    report = gate.validate_manifest_instances({"cases": [
        CSS_CASE, {"environment": "unconfigured", "difficulty": "easy", "seed": 0},
    ]}, include_slow=True)
    assert not report["instance_coverage_complete"]
    assert report["missing_references"] == ["unconfigured"]
    assert [row["reason"] for row in report["cases"]] == [
        "not_run_until_all_references_configured", "reference_not_configured"
    ]


def test_config_drift_rejected_before_judge_or_provider(monkeypatch):
    monkeypatch.setattr(gate.env_runner, "reset", lambda *_args: pytest.fail("must not generate"))
    row = gate.validate_case({**CSS_CASE, "config_path": "envs/weird_machine/css_state_machine/config.yaml",
                              "config_sha256": "0" * 64})
    assert row["status"] == "blocked" and row["reason"] == "pinned_config_drift"
    assert row["provider_calls"] == 0


def test_agent_reset_must_match_oracle_byte_for_byte(tmp_path):
    original = tmp_path / "original"
    judge = tmp_path / "env" / "judge"
    original.mkdir()
    judge.mkdir(parents=True)
    (original / "solution.py").write_text("pass\n", encoding="utf-8")
    (judge / "judge.py").write_text("pass\n", encoding="utf-8")
    state = {"env": "css_state_machine", "difficulty": "easy,easy", "seed": 0,
             "original_workspace": str(original), "env_dir": str(judge.parent)}
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    oracle = {"status": "passed", "instance_sha256": gate._instance_hash(state)}
    assert gate.verify_reset_matches_oracle(oracle, tmp_path, "css_state_machine", "easy,easy", 0) == oracle["instance_sha256"]
    with pytest.raises(ValueError, match="vector/seed"):
        gate.verify_reset_matches_oracle(oracle, tmp_path, "css_state_machine", "easy,easy", 1)
    (judge / "judge.py").write_text("# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from the reference-graded"):
        gate.verify_reset_matches_oracle(oracle, tmp_path, "css_state_machine", "easy,easy", 0)


@pytest.mark.parametrize("seed", [0, 2])
def test_css_triple_uses_real_generated_judge_and_plausible_wrong_fails(seed):
    pytest.importorskip("torch")
    row = gate.validate_case({**CSS_CASE, "seed": seed})
    assert row["status"] == "passed", row
    assert [v["variant"] for v in row["variants"]] == [
        "no_op", "plausible_wrong", "transcription", "reference",
    ]
    scores = [v["score"] for v in row["variants"]]
    assert scores[0] == 0 and scores[1] == pytest.approx(0.416667)
    assert scores[2] < 1 and scores[3] == 1
    wrong = row["variants"][1]
    assert wrong["checks"]["patch_valid"] is True
    assert wrong["checks"]["rule_structure"] is True
    assert wrong["checks"]["parity_correctness"] is False
    transcription = row["variants"][2]
    assert transcription["checks"]["patch_valid"] is True
    assert transcription["checks"]["rule_structure"] is True
    assert transcription["checks"]["parity_correctness"] is False
    assert all(v["accepted"] for v in row["variants"])


def test_wrong_submission_that_passes_is_not_silently_accepted(monkeypatch):
    pytest.importorskip("torch")
    entry = gate.REFERENCES["css_state_machine"]
    reference, negative_check = entry[0], entry[1]
    monkeypatch.setitem(gate.REFERENCES, "css_state_machine",
                        (lambda workspace, *, wrong: reference(workspace, wrong=False), negative_check))
    row = gate.validate_case(CSS_CASE)
    assert row["status"] == "blocked" and row["reason"] == "plausible_wrong_did_not_grade_as_expected"
    assert row["variants"][-1]["score"] == 1
    assert row["variants"][-1]["accepted"] is False
    assert row["provider_calls"] == 0


def test_oracle_with_unknown_failure_mode_never_counts_as_negative_evidence():
    row = {"done": True, "verdict": "FAIL", "score": 0.0,
           "failure_mode": "unknown", "checks": {"patch_valid": True, "parity_correctness": False}}
    assert not gate._check(row, "plausible_wrong", "parity_correctness")
    row["failure_mode"] = "underfit"
    assert gate._check(row, "plausible_wrong", "parity_correctness")


def test_instance_report_does_not_expose_patch_contents(tmp_path):
    pytest.importorskip("torch")
    row = gate.validate_case(CSS_CASE)
    assert row["status"] == "passed"
    assert len(row["instance_sha256"]) == 64
    assert all(len(v["patch_sha256"]) == 64 for v in row["variants"])
    assert "class CSSLogicEngine" not in json.dumps(row)
