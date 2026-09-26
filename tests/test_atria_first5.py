from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from arena.providers import Completion
from tools import atria_first_experiment
from tools.atria_first_experiment import (
    APPROVED_BASE,
    APPROVED_MODEL,
    PROFILE_DEFAULT,
    _compatibility_check,
    _validate_profile,
)
from tools.atria_modality import inventory_selected_modalities
from tools.first_experiment import EXPECTED_CASES, _select_manifest
from tools.run_suite import _build_command

ROOT = Path(__file__).resolve().parents[1]


def test_atria_profile_and_inventory_are_bounded_and_text_explicit():
    profile = _validate_profile(PROFILE_DEFAULT)
    manifest = _select_manifest(profile, PROFILE_DEFAULT)
    modality = inventory_selected_modalities(manifest, root=ROOT)
    assert profile["provider"] == "atria"
    assert profile["model"] == APPROVED_MODEL
    assert profile["api_base"] == APPROVED_BASE
    assert profile["api_key_env"] == "ATRIA_API_KEY"
    assert profile["stream"] is False
    assert profile["concurrency"] == 1
    assert profile["seed"] == 0
    assert profile["reasoning_mode"] == "provider_default_uncontrolled"
    assert profile["request_extra"] == {}
    assert profile["quota_ceiling_tokens"] is None
    assert [(case["environment"], case["difficulty"]) for case in manifest["cases"]] == EXPECTED_CASES
    assert modality["provider_input_modality"] == "text_only"
    assert modality["selected_case_count"] == 5
    assert modality["unsupported_case_ids"] == []
    assert modality["conversion_performed"] is False
    assert modality["omitted_case_ids"] == []
    glyph = next(item for item in modality["environments"] if item["environment"] == "glyph")
    assert "image" in glyph["non_text_references_in_generated_source"]
    assert glyph["requires_non_text_input"] is False


def test_atria_blocks_failed_instance_oracle_before_any_provider_access(tmp_path, monkeypatch):
    monkeypatch.setattr(
        atria_first_experiment, "validate_manifest_instances",
        lambda *args, **kwargs: {"instance_coverage_complete": False, "cases": [
            {"environment": "glyph", "status": "blocked", "reason": "reference_did_not_grade_as_expected"}]},
    )
    def no_provider_or_runtime(*args, **kwargs):
        raise AssertionError("provider/runtime setup must not be reached")

    monkeypatch.setattr(atria_first_experiment, "_runtime_check", no_provider_or_runtime)
    monkeypatch.setattr(atria_first_experiment, "_optional_credentials", no_provider_or_runtime)
    monkeypatch.setattr(atria_first_experiment, "_compatibility_check", no_provider_or_runtime)
    output = tmp_path / "blocked_pilot"
    assert atria_first_experiment.main(["--out", str(output)]) == 2
    oracle = json.loads((output / "oracle_preflight.json").read_text(encoding="utf-8"))
    report = json.loads((output / "pilot_report.json").read_text(encoding="utf-8"))
    assert oracle["behavioral_coverage_complete"] is False
    assert set(oracle["unverified_environments"]) == {
        "regex_state_machine", "categorical_lenses", "rd_state_carry", "glyph"
    }
    assert oracle["operator_compile_only_override"] is False
    assert report["status"] == "blocked"
    assert report["reason"] == "instance_oracle_coverage_incomplete"
    assert json.loads((output / "instance_oracles.json").read_text())["instance_coverage_complete"] is False


def test_atria_compile_only_override_is_explicit_and_still_uses_no_provider_without_key(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        atria_first_experiment, "validate_manifest_instances",
        lambda *args, **kwargs: {"instance_coverage_complete": True, "cases": []},
    )
    monkeypatch.setattr(atria_first_experiment, "_runtime_check", lambda: {"available": True})
    monkeypatch.setattr(atria_first_experiment, "_optional_credentials", lambda profile: None)
    output = tmp_path / "operator_override"
    assert atria_first_experiment.main([
        "--allow-compile-only-oracles", "--out", str(output)
    ]) == 3
    oracle = json.loads((output / "oracle_preflight.json").read_text(encoding="utf-8"))
    assert oracle["operator_compile_only_override"] is True
    report = json.loads((output / "pilot_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "prepared"
    assert report["usage"]["actual"]["total_tokens"] == 0


def test_atria_override_cannot_bypass_instance_oracle_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        atria_first_experiment, "validate_manifest_instances",
        lambda *args, **kwargs: {"instance_coverage_complete": False, "cases": [
            {"status": "blocked", "reason": "reference_did_not_grade_as_expected"}]},
    )
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no provider/credential access after oracle failure")

    monkeypatch.setattr(atria_first_experiment, "_optional_credentials", forbidden)
    monkeypatch.setattr(atria_first_experiment, "_compatibility_check", forbidden)
    output = tmp_path / "blocked_override"
    assert atria_first_experiment.main(["--allow-compile-only-oracles", "--out", str(output)]) == 2
    report = json.loads((output / "pilot_report.json").read_text(encoding="utf-8"))
    assert report["reason"] == "instance_oracle_coverage_incomplete"


def test_atria_compatibility_fake_uses_shared_nonstreaming_client_and_telemetry(tmp_path, monkeypatch):
    calls: list[dict] = []

    class FakeProvider:
        http_attempts_used = 1
        last_retry_count = 0
        last_attempt_logs = [
            {
                "status_code": 200,
                "response_headers": {
                    "x-rpm-limit": "60",
                    "x-rpm-remaining": "59",
                },
            }
        ]

        def __init__(self, provider, api_key, **kwargs):
            calls.append({"provider": provider, "api_key": api_key, "kwargs": kwargs})

        def complete(self, **kwargs):
            calls.append(kwargs)
            return Completion(
                content="READY",
                requested_model=kwargs["model"],
                resolved_model="Atria-Dawn-Preview",
                finish_reason="stop",
                usage={"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10},
                raw_response={"id": "chatcmpl-fake"},
                latency_ms=12,
                request_id="atria-request-fake",
                response_headers={
                    "x-rpm-limit": "60",
                    "x-rpm-remaining": "59",
                },
                status_code=200,
                reasoning_content_length=None,
            )

    monkeypatch.setattr(atria_first_experiment, "ProviderClient", FakeProvider)
    profile = _validate_profile(PROFILE_DEFAULT)
    result = _compatibility_check(
        profile,
        SimpleNamespace(api_key="offline-fake-secret"),
        tmp_path / "compatibility.json",
    )
    assert result["status"] == "passed"
    assert result["resolved_model"] == APPROVED_MODEL
    assert result["usage"]["total_tokens"] == 10
    assert result["request_id"] == "atria-request-fake"
    assert result["effective_request"]["stream"] is False
    assert result["effective_request"]["request_extra"] == {}
    assert result["effective_request"]["reasoning_mode"] == "provider_default_uncontrolled"
    assert calls[0]["provider"] == "atria"
    assert calls[0]["api_key"] == "offline-fake-secret"
    assert calls[0]["kwargs"]["api_base"] == APPROVED_BASE
    assert calls[0]["kwargs"]["min_interval_seconds"] == 1.1
    assert calls[1]["request_extra"] == {}
    saved = json.loads((tmp_path / "compatibility.json").read_text(encoding="utf-8"))
    assert saved["attempt_logs"][0]["response_headers"]["x-rpm-remaining"] == "59"
    assert "offline-fake-secret" not in (tmp_path / "compatibility.json").read_text(encoding="utf-8")


def test_suite_runner_propagates_provider_pacing_to_episode_command():
    command = _build_command(
        {
            "environment": "glyph",
            "difficulty": "easy,easy,easy,easy,easy,easy",
            "seed": 0,
        },
        provider="atria",
        model=APPROVED_MODEL,
        api_key_env="ATRIA_API_KEY",
        secrets=None,
        api_base=APPROVED_BASE,
        sandbox="docker",
        output_dir=Path("runs/atria-test"),
        max_steps=20,
        max_tokens=8192,
        invalid_retries=1,
        max_http_attempts=1200,
        provider_min_interval_seconds=1.1,
        max_retries=5,
        keep_images=False,
        keep_workspace=False,
    )
    assert "--provider-min-interval-seconds" in command
    assert command[command.index("--provider-min-interval-seconds") + 1] == "1.1"


def test_atria_profile_does_not_allow_guessed_reasoning_fields(tmp_path):
    source = PROFILE_DEFAULT.read_text(encoding="utf-8")
    modified = source.replace("request_extra: {}", "request_extra:\n  reasoning_effort: high")
    path = tmp_path / "atria.yaml"
    path.write_text(modified, encoding="utf-8")
    try:
        _validate_profile(path)
    except ValueError as exc:
        assert "reasoning" in str(exc) or "request_extra" in str(exc)
    else:
        raise AssertionError("guessed reasoning control must be rejected")
