from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import arena.trajectory_runner as trajectory_runner
from arena.providers import Completion, ProviderError
from arena.trajectory import make_messages, normalize_answer, score_answer
from arena.trajectory_runner import (
    TrajectoryOptions,
    parse_seed_range,
    plan_for_options,
    run_trajectory,
    write_summary,
)
from shared.trajectory_semantics import certify_system_pair, make_case
from shared.trajectory_semantics.abstract_semantics import valid_relay
from shared.trajectory_semantics.relabel import make_mapping
from shared.trajectory_semantics.render_flat import render_flat
from shared.trajectory_semantics.rendered_parser import concrete_rollout, parse_rendered

ROOT = Path(__file__).resolve().parents[1]


def test_relay_certification_is_independent_and_relabeling_stable():
    for seed in (0, 1, 7):
        certificate = certify_system_pair(seed)
        assert certificate.certified
        first = make_case(
            system_seed=seed,
            initial_state_seed=0,
            presentation_seed=1000 + seed,
            representation="flat",
            witness_state="valid",
            query_type="complete_return",
            horizon=6,
            relabeling="canonical",
            certification=certificate.as_dict(),
        )
        second = make_case(
            system_seed=seed,
            initial_state_seed=0,
            presentation_seed=1000 + seed,
            representation="reflective",
            witness_state="valid",
            query_type="complete_return",
            horizon=6,
            relabeling="permuted_templates",
            certification=certificate.as_dict(),
        )
        assert first.semantic_equivalence_id == second.semantic_equivalence_id
        assert first.matched_control_id != second.matched_control_id
        assert first.expected_answer == "yes"
        assert second.expected_answer == "yes"
        assert first.witness_applicable is True
        broken = make_case(
            system_seed=seed,
            initial_state_seed=0,
            presentation_seed=1000 + seed,
            representation="flat",
            witness_state="broken",
            query_type="complete_return",
            horizon=6,
            relabeling="canonical",
            certification=certificate.as_dict(),
        )
        assert broken.expected_answer == "no"
        assert broken.stale_witness_prediction == "yes"
        expected_valid_c = (
            "C(payload) -> A(payload)"
            if seed % 4 in {0, 1}
            else "C(payload) -> A(flip(payload))"
        )
        assert expected_valid_c in first.spec_text
        assert "C(payload) -> A(1)" in broken.spec_text


def test_concrete_rollout_does_not_use_abstract_transition_method():
    parsed = parse_rendered(render_flat(valid_relay(system_seed=0), make_mapping("canonical")))
    altered = replace(
        parsed,
        system=replace(
            parsed.system,
            rules=tuple(replace(rule, target="A") for rule in parsed.system.rules),
        ),
    )
    assert concrete_rollout(altered, "A(0)", 1) == ("B", 0)


def test_resource_protocols_are_explicit_and_answers_are_normalized():

    case = make_case(
        semantic_seed=0,
        representation="flat",
        witness_state="valid",
        query_type="state_at_T",
        horizon=30,
        relabeling="canonical",
        resource_protocol="external_scratchpad",
        certification=certify_system_pair(0).as_dict(),
    )
    assert "scratchpad" in make_messages(case, "external_scratchpad")[0]["content"]
    assert normalize_answer("FINAL: A(0)\n") == "a(0)"
    score = score_answer(case, f"FINAL: {case.expected_answer}")
    assert score["correct"] is True
    assert score["matched_stale_witness_prediction"] is False


def test_seed_range_is_inclusive():
    assert parse_seed_range("0:2,7") == [0, 1, 2, 7]


def test_plan_conditions_horizons_and_budget():
    options = TrajectoryOptions(
        provider="custom",
        model="offline",
        out=Path("unused"),
        representations=["flat"],
        witnesses=["valid", "broken"],
        queries=["parse_only", "one_step", "complete_return"],
        horizons=[6, 30],
        relabelings=["canonical"],
        syntax_noise=["clean"],
        semantic_seeds=[0, 1],
        system_seeds=[0, 1],
        initial_state_seeds=[0, 0],
        presentation_seeds=[100, 101],
        api_replications=2,
        max_tokens=17,
    )
    plan = plan_for_options(options)
    assert plan.horizon_counts == {
        "parse_only": [0],
        "one_step": [1],
        "complete_return": [6, 30],
    }
    assert plan.case_count == 2 * 2 * (1 + 1 + 2)
    assert plan.api_call_count == plan.case_count * 2
    assert plan.maximum_output_token_budget == plan.api_call_count * 17


def test_limit_reduces_guarded_execution_calls():
    options = TrajectoryOptions(
        provider="custom",
        model="offline",
        out=Path("unused"),
        representations=["flat"],
        witnesses=["valid"],
        queries=["state_at_T"],
        horizons=[6, 30],
        relabelings=["canonical"],
        syntax_noise=["clean"],
        semantic_seeds=[0],
        system_seeds=[0],
        initial_state_seeds=[0],
        presentation_seeds=[100],
        limit=2,
        max_calls=2,
    )
    plan = plan_for_options(options)
    from arena.trajectory_runner import enforce_call_guard

    enforce_call_guard(options, plan)


def test_summary_keeps_witness_siblings_separate_and_attaches_controls(tmp_path):
    certificate = certify_system_pair(0).as_dict()
    valid = make_case(
        system_seed=0,
        initial_state_seed=0,
        presentation_seed=100,
        representation="flat",
        witness_state="valid",
        query_type="complete_return",
        horizon=6,
        relabeling="canonical",
        certification=certificate,
    )
    broken = make_case(
        system_seed=0,
        initial_state_seed=0,
        presentation_seed=100,
        representation="flat",
        witness_state="broken",
        query_type="complete_return",
        horizon=6,
        relabeling="canonical",
        certification=certificate,
    )
    records = []
    for case, answer in ((valid, "yes"), (broken, "yes")):
        records.append(
            {
                "event": "case_result",
                "case_id": case.case_id,
                "case": case.as_dict(),
                "api_replication": 0,
                "correct": answer == case.expected_answer,
                "format_valid": True,
                "matched_stale_witness_prediction": answer == "yes" and answer != case.expected_answer,
            }
        )
    summary = write_summary(tmp_path, records, {})
    assert summary["group_count"] == 2
    assert {row["benchmark_status"] for row in summary["groups"]} == {
        "witness_valid",
        "witness_broken",
    }
    assert all(row["parse_control_n"] == 0 for row in summary["groups"])


def test_summary_keeps_syntax_and_resource_variants_separate(tmp_path):
    certificate = certify_system_pair(0).as_dict()
    cases = [
        make_case(
            system_seed=0,
            initial_state_seed=0,
            presentation_seed=100,
            representation="flat",
            witness_state="valid",
            query_type="complete_return",
            horizon=6,
            relabeling="canonical",
            syntax_noise=syntax_noise,
            resource_protocol=resource_protocol,
            certification=certificate,
        )
        for syntax_noise, resource_protocol in (("clean", "answer_only"), ("noisy", "external_scratchpad"))
    ]
    records = [
        {
            "event": "case_result",
            "case_id": case.case_id,
            "case": case.as_dict(),
            "api_replication": 0,
            "correct": True,
            "format_valid": True,
            "matched_stale_witness_prediction": False,
        }
        for case in cases
    ]
    summary = write_summary(tmp_path, records, {})
    assert summary["group_count"] == 2
    assert {
        (row["syntax_noise"], row["resource_protocol"])
        for row in summary["groups"]
    } == {("clean", "answer_only"), ("noisy", "external_scratchpad")}


def test_fake_provider_attaches_controls_and_excludes_only_failed_reflective_rows(
    tmp_path, monkeypatch
):
    class FakeProviderClient:
        last_retry_count = 0
        last_attempts = []

        def __init__(self, provider, api_key, **kwargs):
            self.provider = provider

        def complete(self, *, model, messages, max_tokens, temperature):
            prompt = messages[-1]["content"]
            if "Parsing control" in prompt:
                answer = "flip" if "reflective-relay-v1" in prompt else "same"
            elif "after exactly 1 transition" in prompt:
                answer = "B(0)"
            else:
                answer = "yes"
            return Completion(
                content=answer,
                requested_model=model,
                resolved_model=model,
                finish_reason="stop",
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                raw_response={"model": model},
                latency_ms=1,
                request_id="fake-request",
                response_headers={},
                provider=self.provider,
            )

    monkeypatch.setattr(trajectory_runner, "ProviderClient", FakeProviderClient)
    result = run_trajectory(
        TrajectoryOptions(
            provider="custom",
            model="fake/model",
            out=tmp_path / "run",
            representations=["flat", "reflective"],
            witnesses=["valid"],
            queries=["parse_only", "one_step", "complete_return"],
            horizons=[6],
            relabelings=["canonical"],
            syntax_noise=["clean"],
            semantic_seeds=[0],
            system_seeds=[0],
            initial_state_seeds=[0],
            presentation_seeds=[100],
            api_key="fake-secret",
            api_base="https://example.invalid/v1",
            max_tokens=8,
            max_calls=6,
        )
    )
    trajectory_rows = {
        row["representation"]: row
        for row in result["summary"]["groups"]
        if row["query_type"] == "complete_return"
    }
    assert trajectory_rows["flat"]["parse_control_passed"] is True
    assert trajectory_rows["flat"]["one_step_control_passed"] is True
    assert trajectory_rows["flat"]["conditional_n"] == 1
    assert trajectory_rows["reflective"]["parse_control_passed"] is False
    assert trajectory_rows["reflective"]["one_step_control_passed"] is True
    assert trajectory_rows["reflective"]["conditional_n"] == 0
    assert result["summary"]["trajectory_cases"] == 2
    assert result["summary"]["unconditional_trajectory_accuracy"] == 1.0
    assert result["summary"]["conditional_trajectory_cases"] == 1
    assert result["summary"]["excluded_trajectory_cases"] == 1

    trace_records = [
        json.loads(line)
        for line in (tmp_path / "run" / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    trace_trajectory = {
        record["case"]["representation"]: record
        for record in trace_records
        if record.get("event") == "case_result"
        and record["case"]["query_type"] == "complete_return"
    }
    assert trace_trajectory["flat"]["parse_control_passed"] is True
    assert trace_trajectory["reflective"]["parse_control_passed"] is False


def test_conditional_accuracy_is_nullable_and_not_zero_for_empty_sample(tmp_path):
    certificate = certify_system_pair(0).as_dict()

    def case(query: str, horizon: int):
        return make_case(
            system_seed=0,
            initial_state_seed=0,
            presentation_seed=100,
            representation="flat",
            witness_state="valid",
            query_type=query,
            horizon=horizon,
            relabeling="canonical",
            certification=certificate,
        )

    def result(case_value, correct: bool, replication: int = 0) -> dict[str, object]:
        return {
            "event": "case_result",
            "case_id": case_value.case_id,
            "case": case_value.as_dict(),
            "api_replication": replication,
            "correct": correct,
            "format_valid": True,
            "matched_stale_witness_prediction": False,
        }

    no_controls = [result(case("complete_return", 6), True)]
    empty_summary = write_summary(tmp_path / "empty", no_controls, {})
    assert empty_summary["conditional_trajectory_accuracy"] is None
    assert empty_summary["groups"][0]["conditional_accuracy"] is None

    def records_for(correct_trajectory: list[bool]) -> list[dict[str, object]]:
        records = [result(case("parse_only", 0), True), result(case("one_step", 1), True)]
        records.extend(
            result(case("complete_return", horizon), correct)
            for horizon, correct in zip((6, 30, 126), correct_trajectory, strict=True)
        )
        return records

    zero_summary = write_summary(tmp_path / "zero", records_for([False, False, False]), {})
    assert zero_summary["conditional_trajectory_cases"] == 3
    assert zero_summary["conditional_trajectory_accuracy"] == 0.0

    partial_summary = write_summary(tmp_path / "partial", records_for([True, True, False]), {})
    assert partial_summary["conditional_trajectory_cases"] == 3
    assert partial_summary["conditional_trajectory_accuracy"] == 2 / 3


def test_provider_error_is_not_reported_as_observed_control_failure(tmp_path, monkeypatch):
    class TimeoutProviderClient:
        last_retry_count = 0
        last_attempts = []

        def __init__(self, provider, api_key, **kwargs):
            self.provider = provider

        def complete(self, *, model, messages, max_tokens, temperature):
            prompt = messages[-1]["content"]
            if "Parsing control" in prompt and "reflective-relay-v1" in prompt:
                raise ProviderError(
                    "Provider request timed out",
                    body="timed out",
                    retryable=True,
                    attempts=1,
                )
            if "Parsing control" in prompt:
                answer = "same"
            elif "after exactly 1 transition" in prompt:
                answer = "B(0)"
            else:
                answer = "yes"
            return Completion(
                content=answer,
                requested_model=model,
                resolved_model=model,
                finish_reason="stop",
                usage={"prompt_tokens": 1, "completion_tokens": 1},
                raw_response={"model": model},
                latency_ms=1,
                request_id="fake-request",
                response_headers={},
                provider=self.provider,
            )

    monkeypatch.setattr(trajectory_runner, "ProviderClient", TimeoutProviderClient)
    result = run_trajectory(
        TrajectoryOptions(
            provider="custom",
            model="fake/model",
            out=tmp_path / "run",
            representations=["flat", "reflective"],
            witnesses=["valid"],
            queries=["parse_only", "one_step", "complete_return"],
            horizons=[6],
            relabelings=["canonical"],
            syntax_noise=["clean"],
            semantic_seeds=[0],
            system_seeds=[0],
            initial_state_seeds=[0],
            presentation_seeds=[100],
            api_key="fake-secret",
            api_base="https://example.invalid/v1",
            max_tokens=8,
            max_calls=6,
        )
    )
    reflective = next(
        row
        for row in result["summary"]["groups"]
        if row["representation"] == "reflective" and row["query_type"] == "complete_return"
    )
    assert reflective["parse_control_status"] == "api_error"
    assert reflective["parse_control_passed"] is None
    assert reflective["conditional_n"] == 0
    assert reflective["conditional_missing_control_n"] == 0
    assert reflective["conditional_failed_control_n"] == 0
    assert reflective["conditional_api_error_control_n"] == 1
    assert result["summary"]["api_error_control_trajectory_cases"] == 1


def test_control_replications_are_keyed_and_duplicate_controls_rejected(tmp_path):
    certificate = certify_system_pair(0).as_dict()
    cases = {
        query: make_case(
            system_seed=0,
            initial_state_seed=0,
            presentation_seed=100,
            representation="flat",
            witness_state="valid",
            query_type=query,
            horizon=6,
            relabeling="canonical",
            certification=certificate,
        )
        for query in ("parse_only", "one_step", "complete_return")
    }

    def record(query: str, replication: int, correct: bool) -> dict[str, object]:
        case = cases[query]
        return {
            "event": "case_result",
            "case_id": case.case_id,
            "case": case.as_dict(),
            "api_replication": replication,
            "correct": correct,
            "format_valid": True,
            "matched_stale_witness_prediction": False,
        }

    records = [
        record("complete_return", 1, True),
        record("parse_only", 1, False),
        record("one_step", 1, True),
        record("complete_return", 0, True),
        record("parse_only", 0, True),
        record("one_step", 0, True),
    ]
    summary = write_summary(tmp_path / "ordered", records, {})
    trajectory_records = {
        item["api_replication"]: item
        for item in records
        if item["case"]["query_type"] == "complete_return"
    }
    assert trajectory_records[0]["parse_control_passed"] is True
    assert trajectory_records[1]["parse_control_passed"] is False
    assert summary["conditional_trajectory_cases"] == 1
    assert summary["failed_control_trajectory_cases"] == 1
    assert summary["missing_control_trajectory_cases"] == 0

    reversed_summary = write_summary(tmp_path / "reversed", list(reversed(records)), {})
    assert reversed_summary["conditional_trajectory_cases"] == 1
    assert reversed_summary["failed_control_trajectory_cases"] == 1

    duplicate = record("parse_only", 0, False)
    duplicate["case"] = {**duplicate["case"], "case_id": "duplicate-parse"}
    duplicate["case_id"] = "duplicate-parse"
    with pytest.raises(ValueError, match="duplicate control result"):
        write_summary(tmp_path / "duplicate", records + [duplicate], {})


def test_trajectory_environments_generate_and_compile():


    names = ["pytest_ts_parse", "pytest_ts_one", "pytest_ts_trajectory"]
    cases = [
        ("ts_parse_only", "valid,flat"),
        ("ts_one_step", "broken,reflective"),
        ("ts_trajectory", "valid,flat"),
    ]
    try:
        for name, (environment, difficulty) in zip(names, cases, strict=True):
            subprocess.run(["rm", "-rf", name], cwd=ROOT, check=False)
            result = subprocess.run(
                [
                    sys.executable,
                    "generate_env.py",
                    "--env",
                    environment,
                    "--name",
                    name,
                    "--difficulty",
                    difficulty,
                    "--seed",
                    "11",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            generated = ROOT / name
            assert (generated / "agent/workspace/prompt.md").is_file()
            assert (generated / "judge/judge.py").is_file()
            files = [str(path) for path in generated.rglob("*.py")]
            subprocess.run([sys.executable, "-m", "py_compile", *files], check=True)
            contents = "\n".join(
                path.read_text(errors="ignore") for path in generated.rglob("*") if path.is_file()
            )
            assert "%%" not in contents
    finally:
        for name in names:
            shutil.rmtree(ROOT / name, ignore_errors=True)


def test_offline_judge_scores_stale_witness_as_diagnostic(tmp_path):
    case = {
        "case_id": "broken-case",
        "query_type": "complete_return",
        "expected_answer": "no",
        "stale_witness_prediction": "yes",
        "initial_state": {"payload": "0"},
    }
    (tmp_path / "cases.jsonl").write_text(json.dumps(case) + "\n", encoding="utf-8")
    (tmp_path / "answers.jsonl").write_text(
        json.dumps({"case_id": "broken-case", "raw_model_output": "yes"}) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "results.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "docker/trajectory_judge.py",
            "--cases",
            str(tmp_path / "cases.jsonl"),
            "--answers",
            str(tmp_path / "answers.jsonl"),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert '"accuracy": 0.0' in result.stdout
    scored = json.loads(output.read_text().splitlines()[0])
    assert scored["matched_stale_witness_prediction"] is True
    assert scored["correct"] is False
