import csv
import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

from arena.artifacts import RunArtifacts, summarize_run
from arena.result_record import SCHEMA_VERSION, build_attempt_record

ROOT = Path(__file__).resolve().parents[1]


def _record(final, *, traces=(), responses=(), errors=()):
    return build_attempt_record(
        attempt_id="attempt-1",
        case_id="case-1",
        campaign_id="campaign-1",
        environment="synthetic_env",
        difficulty="easy",
        seed=17,
        judge_guarantee="behavioral_reference",
        final=final,
        traces=traces,
        model_responses=responses,
        api_errors=errors,
    )


def _stage(record, name):
    return record["stages"][name]


def test_provider_failure_is_not_a_behavioral_score():
    record = _record(
        {"verdict": "FAIL", "score": 0.0, "failure_mode": "api_error", "notes": ["unavailable"]},
        traces=[{"event": "provider_error", "parse_error": "provider request failed"}],
        errors=[{"status": 503}],
    )

    assert record["case_disposition"] == "unscored"
    assert _stage(record, "provider_transport")["status"] == "failed"
    assert _stage(record, "provider_transport")["code"] == "provider_error"
    assert _stage(record, "response_parsing")["status"] == "not_reached"
    assert _stage(record, "behavioral_evaluation")["status"] == "not_reached"
    assert record["failure_mode"] == "api_error"


def test_malformed_action_is_separate_from_provider_failure():
    record = _record(
        {"verdict": "FAIL", "score": 0.0, "failure_mode": "invalid_action", "notes": ["bad JSON"]},
        traces=[{"raw_model_output": "not JSON", "parsed_action": None, "parse_error": "invalid JSON", "invalid_action_attempts": 2}],
        responses=[{"turn": 1}],
    )

    assert _stage(record, "provider_transport")["status"] == "passed"
    assert _stage(record, "response_parsing")["status"] == "failed"
    assert _stage(record, "response_parsing")["code"] == "malformed_action"
    assert _stage(record, "behavioral_evaluation")["status"] == "not_reached"
    assert record["case_disposition"] == "rejected"


def test_empty_patch_is_distinct_from_missing_required_file():
    empty_patch = _record(
        {
            "verdict": "FAIL",
            "score": 0.0,
            "failure_mode": "patch_invalid",
            "notes": ["Patch validation failed: Patch file is empty"],
            "events": [{"action": "patch_invalid", "status": "fail", "summary": "Patch file is empty"}],
            "stage_outcomes": {"patch_validation": {"status": "failed", "code": "empty_patch"}},
        }
    )
    missing_required_file = _record(
        {
            "verdict": "FAIL",
            "score": 0.5,
            "raw_accuracy": 0.5,
            "failure_mode": "overfit_visible_tests",
            "checks": {"required_multifile_edit": False, "hidden_metric_passed": False},
            "metrics": {"missing_required_files": ["policy.py"]},
            "stage_outcomes": {"behavioral_evaluation": {"status": "scored_fail", "code": "underfit"}},
        }
    )

    assert _stage(empty_patch, "patch_validation") == {"status": "failed", "code": "empty_patch"}
    assert _stage(empty_patch, "behavioral_evaluation")["status"] == "not_reached"
    assert empty_patch["case_disposition"] == "rejected"
    assert _stage(missing_required_file, "patch_validation")["status"] == "passed"
    assert _stage(missing_required_file, "required_artifacts")["code"] == "required_file_missing"
    assert _stage(missing_required_file, "behavioral_evaluation")["status"] == "scored_fail"
    assert missing_required_file["case_disposition"] == "scored"


def test_missing_answer_artifact_is_recorded_as_a_pre_behavior_rejection():
    record = _record(
        {
            "verdict": "FAIL",
            "score": 0.0,
            "failure_mode": "answer_format_invalid",
            "notes": ["answer.py extraction failed: answer.py not found"],
            "events": [{"action": "answer_format_invalid", "status": "fail", "summary": "answer.py not found"}],
        }
    )

    assert _stage(record, "required_artifacts")["status"] == "failed"
    assert _stage(record, "required_artifacts")["code"] == "required_file_missing"
    assert _stage(record, "behavioral_evaluation")["status"] == "not_reached"
    assert record["case_disposition"] == "rejected"


def test_syntax_error_is_not_misreported_as_runtime_or_behavioral_failure():
    record = _record(
        {
            "verdict": "FAIL",
            "score": 0.0,
            "failure_mode": "source_invalid",
            "stage_outcomes": {"source_validation": {"status": "failed", "code": "syntax_error"}},
        }
    )

    assert _stage(record, "source_validation")["status"] == "failed"
    assert _stage(record, "source_validation")["code"] == "syntax_error"
    assert _stage(record, "runtime_execution")["status"] == "not_reached"
    assert _stage(record, "behavioral_evaluation")["status"] == "not_reached"
    assert record["case_disposition"] == "rejected"


def test_runtime_error_and_wrong_output_have_distinct_dispositions():
    runtime_error = _record(
        {
            "verdict": "FAIL",
            "score": 0.0,
            "failure_mode": "timeout",
            "stage_outcomes": {"runtime_execution": {"status": "failed", "code": "timeout"}},
        }
    )
    wrong_output = _record(
        {
            "verdict": "FAIL",
            "score": 0.4,
            "raw_accuracy": 0.4,
            "failure_mode": "underfit",
            "checks": {"hidden_metric_passed": False},
            "stage_outcomes": {"behavioral_evaluation": {"status": "scored_fail", "code": "wrong_output"}},
        }
    )

    assert _stage(runtime_error, "runtime_execution")["status"] == "failed"
    assert runtime_error["case_disposition"] == "unscored"
    assert _stage(wrong_output, "behavioral_evaluation")["status"] == "scored_fail"
    assert wrong_output["case_disposition"] == "scored"


def test_legacy_failure_mode_is_not_used_as_stage_evidence():
    record = _record(
        {"verdict": "FAIL", "score": 0.0, "failure_mode": "patch_invalid"}
    )

    assert _stage(record, "patch_validation")["status"] == "unknown"
    assert record["case_disposition"] == "unscored"
    assert record["failure_mode"] == "patch_invalid"


def test_raw_score_fields_are_preserved_without_reconciliation():
    final = {
        "verdict": "FAIL",
        "score": 0.75,
        "raw_accuracy": 0.3,
        "failure_mode": "underfit",
        "metrics": {"trusted_score": 0.4, "score": 0.9},
        "checks": {"first": True, "second": False},
        "notes": ["raw diagnostic"],
        "stage_outcomes": {"behavioral_evaluation": {"status": "scored_fail", "code": "underfit"}},
    }
    record = _record(final)

    assert record["schema_version"] == SCHEMA_VERSION == 1
    assert record["failure_mode"] == "underfit"
    assert record["raw_scores"] == {
        "verdict": "FAIL",
        "score": 0.75,
        "raw_accuracy": 0.3,
        "metrics": {"trusted_score": 0.4, "score": 0.9},
        "checks": {"first": True, "second": False},
    }
    assert record["failure_mode"] == "underfit"
    assert record["diagnostics"]["notes"] == ["raw diagnostic"]
    assert record["case_id"] == "case-1"
    assert record["campaign_id"] == "campaign-1"
    assert record["judge_guarantee"] == "behavioral_reference"


def test_common_judge_keeps_behavioral_outcome_separate_from_required_artifact_gate(tmp_path, monkeypatch):
    source = (ROOT / "shared" / "judge_lib.py").read_text(encoding="utf-8")
    rendered = source.replace("%%PATCHABLE_FILES%%", '["task.py"]')
    judge_lib_path = tmp_path / "judge_lib.py"
    judge_lib_path.write_text(rendered, encoding="utf-8")

    fake_torch = types.ModuleType("torch")
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    module_name = f"test_judge_lib_{id(tmp_path)}"
    spec = importlib.util.spec_from_file_location(module_name, judge_lib_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)

    result = module.base_result()
    result["_required_files_ok"] = False
    result["stage_outcomes"]["required_artifacts"] = {
        "status": "failed",
        "code": "required_file_missing",
    }
    module.score_from_checks(result, {"behavior_a": True, "behavior_b": True}, 2)
    result["verdict"] = "FAIL"  # full end-to-end reward is capped by the artifact gate
    record = _record(result)

    assert result["failure_mode"] == "overfit_visible_tests"  # preserved legacy diagnostic
    assert result["score"] == 0.95
    assert _stage(record, "required_artifacts")["status"] == "failed"
    assert _stage(record, "behavioral_evaluation")["status"] == "scored_pass"
    assert record["case_disposition"] == "scored"
    assert record["end_to_end_status"] == "failed"

    accuracy_result = module.base_result()
    accuracy_result["_required_files_ok"] = False
    accuracy_result["stage_outcomes"]["required_artifacts"] = {
        "status": "failed",
        "code": "required_file_missing",
    }
    module.score_from_accuracy(
        accuracy_result,
        accuracy=0.99,
        pass_threshold=0.9,
        partial_threshold=0.5,
        anti_gaming_passed=True,
    )
    accuracy_result["verdict"] = "FAIL"
    accuracy_record = _record(accuracy_result)
    assert accuracy_result["score"] == 0.95
    assert _stage(accuracy_record, "behavioral_evaluation")["status"] == "scored_pass"
    assert _stage(accuracy_record, "required_artifacts")["status"] == "failed"


def test_run_artifacts_add_result_record_without_replacing_final_json(tmp_path):
    artifacts = RunArtifacts(tmp_path, "attempt-1")
    final = {
        "verdict": "FAIL",
        "score": 0.25,
        "failure_mode": "underfit",
        "notes": ["kept"],
        "events": [{"action": "scored", "status": "ok"}],
    }
    record = _record(final)
    artifacts.write_manifest({"run_id": "attempt-1", "provider": "custom", "environment": "synthetic_env"})
    artifacts.write_final(final)
    artifacts.write_result_record(record)

    assert json.loads(artifacts.path("final.json").read_text()) == final
    assert json.loads(artifacts.path("result_record.json").read_text()) == record
    csv_path, md_path = summarize_run(artifacts.root)
    with csv_path.open(newline="", encoding="utf-8") as handle:
        summary = next(csv.DictReader(handle))
    assert summary["case_id"] == "case-1"
    assert summary["campaign_id"] == "campaign-1"
    assert summary["case_disposition"] == "scored"
    assert "behavioral_evaluation" in summary["stage_statuses"]
    summary_markdown = md_path.read_text(encoding="utf-8")
    assert "Judge guarantee" in summary_markdown
    assert "Stage statuses" in summary_markdown


def _render_validator(source: str, *, patchable: str) -> str:
    return source.replace("%%PATCHABLE_FILES%%", patchable).replace(
        "%%EXTRA_ALLOWED_IMPORTS%%", ""
    )


def test_patch_validator_emits_machine_readable_empty_patch_code(tmp_path):
    source = (ROOT / "shared" / "patch_validator.py").read_text()
    validator = tmp_path / "patch_validator.py"
    validator.write_text(_render_validator(source, patchable='["task.py"]'))
    originals = tmp_path / "originals"
    originals.mkdir()
    (originals / "task.py").write_text("value = 1\n")
    patch = tmp_path / "empty.patch"
    patch.write_text("")

    env = os.environ.copy()
    env["JUDGE_PATCH_PATH"] = str(patch)
    env["JUDGE_ORIGINALS_DIR"] = str(originals)
    result = subprocess.run(
        [sys.executable, str(validator)], capture_output=True, text=True, env=env, check=False
    )

    assert result.returncode == 1
    assert "FAIL_CODE: empty_patch" in result.stdout


def test_source_validator_emits_syntax_diagnostic(tmp_path):
    source = (ROOT / "shared" / "source_validator.py").read_text()
    validator = tmp_path / "source_validator.py"
    validator.write_text(_render_validator(source, patchable='["task.py"]'))
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "task.py").write_text("def broken(:\n    pass\n")

    result = subprocess.run(
        [sys.executable, str(validator), str(source_dir)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 1
    assert "SyntaxError" in result.stdout


def test_suite_command_threads_case_campaign_and_guarantee_ids(tmp_path):
    from tools.run_suite import _build_command

    command = _build_command(
        {"environment": "synthetic_env", "difficulty": "easy", "seed": 17},
        provider="custom",
        model="offline/test",
        api_key_env="TEST_API_KEY",
        secrets=None,
        api_base=None,
        sandbox="local",
        output_dir=tmp_path,
        max_steps=1,
        max_tokens=8,
        invalid_retries=0,
        keep_images=False,
        keep_workspace=False,
        case_id="case-1",
        campaign_id="campaign-1",
        judge_guarantee="compile_only",
    )

    assert command[command.index("--case-id") + 1] == "case-1"
    assert command[command.index("--campaign-id") + 1] == "campaign-1"
    assert command[command.index("--judge-guarantee") + 1] == "compile_only"


def test_attempt_id_case_id_and_guarantee_are_additive_manifest_fields():
    from arena.artifacts import manifest_defaults

    manifest = manifest_defaults(
        root=ROOT,
        run_id="attempt-1",
        provider="custom",
        api_base="https://example.invalid/v1",
        requested_model="offline/test",
        environment="synthetic_env",
        difficulty="easy",
        seed=17,
        sandbox="local",
        max_steps=1,
        max_tokens=8,
        temperature=0.0,
        request_extra={},
        system_prompt="test",
        campaign_id="campaign-1",
        case_id="case-1",
        attempt_id="attempt-1",
        judge_guarantee="compile_only",
    )

    assert manifest["campaign_id"] == "campaign-1"
    assert manifest["case_id"] == "case-1"
    assert manifest["attempt_id"] == "attempt-1"
    assert manifest["judge_guarantee"] == "compile_only"
