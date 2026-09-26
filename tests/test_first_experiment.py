from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from arena.providers import Completion
from tools import first_experiment
from tools.first_experiment import (
    APPROVED_MODEL,
    EXPECTED_CASES,
    PROFILE_DEFAULT,
    REQUIRED_LIMITS,
    _compatibility_check,
    _select_manifest,
    _validate_profile,
)


def test_nvidia_first5_profile_and_selected_manifest_are_pinned():
    profile = _validate_profile(PROFILE_DEFAULT)
    manifest = _select_manifest(profile, PROFILE_DEFAULT)
    assert profile["model"] == APPROVED_MODEL
    assert profile["temperature"] == 1.0
    assert profile["top_p"] == 0.95
    assert profile["request_extra"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert manifest["case_count"] == 5
    assert manifest["environment_count"] == 5
    assert [
        (case["environment"], case["difficulty"])
        for case in manifest["cases"]
    ] == EXPECTED_CASES
    assert all(len(case["config_sha256"]) == 64 for case in manifest["cases"])
    assert manifest["repository"]["commit"]
    assert manifest["pilot"]["profile_sha256"]
    assert set(manifest["pilot"]["config_hashes"]) == {
        environment for environment, _ in EXPECTED_CASES
    }
    assert profile["limits"] == REQUIRED_LIMITS


def test_nvidia_pilot_blocks_failed_instance_oracles_before_provider_access(tmp_path, monkeypatch):
    monkeypatch.setattr(
        first_experiment, "validate_manifest_instances",
        lambda *args, **kwargs: {"instance_coverage_complete": False, "cases": [
            {"status": "blocked", "reason": "reference_not_configured"}]},
    )
    def forbidden(*args, **kwargs):
        raise AssertionError("provider/runtime setup must not be reached")

    monkeypatch.setattr(first_experiment, "_runtime_check", forbidden)
    monkeypatch.setattr(first_experiment, "_optional_credentials", forbidden)
    output = tmp_path / "blocked_pilot"
    assert first_experiment.main(["--out", str(output)]) == 2
    report = json.loads((output / "pilot_report.json").read_text(encoding="utf-8"))
    oracle = json.loads((output / "oracle_preflight.json").read_text(encoding="utf-8"))
    assert report["status"] == "blocked"
    assert report["reason"] == "instance_oracle_coverage_incomplete"
    assert oracle["behavioral_coverage_complete"] is False
    assert oracle["operator_compile_only_override"] is False


def test_compatibility_fake_requires_stop_and_records_effective_request(tmp_path, monkeypatch):
    seen = []

    class FakeProvider:
        last_retry_count = 1
        http_attempts_used = 2
        last_attempt_logs = [
            {"status_code": 503, "elapsed_ms": 4},
            {"status_code": 200, "elapsed_ms": 6},
        ]

        def __init__(self, provider, api_key, **kwargs):
            seen.append((provider, api_key, kwargs))

        def complete(self, **kwargs):
            return Completion(
                content="READY",
                requested_model=kwargs["model"],
                resolved_model=kwargs["model"],
                finish_reason="stop",
                usage={"completion_tokens": 1},
                raw_response={},
                latency_ms=6,
                request_id="fake-request",
                response_headers={},
                status_code=200,
                reasoning_content_length=None,
            )

    profile = {
        "api_base": "https://example.invalid/v1",
        "model": APPROVED_MODEL,
        "temperature": 1.0,
        "top_p": 0.95,
        "request_extra": {"chat_template_kwargs": {"enable_thinking": False}},
        "limits": {"max_tokens": 8192, "max_retries": 5},
    }
    monkeypatch.setattr(first_experiment, "ProviderClient", FakeProvider)
    output = tmp_path / "compatibility.json"
    result = _compatibility_check(profile, SimpleNamespace(api_key="SECRET"), output)
    assert result["status"] == "passed"
    assert result["attempts"] == 2
    assert result["status_code"] == 200
    assert result["finish_reason"] == "stop"
    assert result["content_length"] == 5
    assert result["effective_request"]["top_p"] == 0.95
    assert result["effective_request"]["request_extra"]["chat_template_kwargs"]["enable_thinking"] is False
    assert seen[0][2]["max_retries"] == 5
    assert seen[0][2]["max_http_attempts"] == 6


def test_nvidia_first5_uses_one_bounded_http_budget():
    profile = _validate_profile(PROFILE_DEFAULT)
    limits = profile["limits"]
    episode_calls = limits["max_steps"] * (1 + limits["invalid_retries"])
    # The baseline five-case plan is 202 HTTP attempts. The configured ceiling
    # also covers the six-attempt worst case for every logical call, including
    # the /models probe and compatibility gate.
    per_logical_call = limits["max_retries"] + 1
    baseline = 2 + 5 * episode_calls
    worst_case = 1 + per_logical_call + 5 * episode_calls * per_logical_call
    assert baseline == 202
    assert per_logical_call == 6
    assert worst_case == 1207
    assert worst_case <= limits["max_http_attempts"]
    assert limits["max_http_attempts"] == 1207
    assert Path(PROFILE_DEFAULT).is_file()
