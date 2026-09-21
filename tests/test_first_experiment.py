from __future__ import annotations

from pathlib import Path

from tools.first_experiment import (
    EXPECTED_CASES,
    PROFILE_DEFAULT,
    REQUIRED_LIMITS,
    _select_manifest,
    _validate_profile,
)


def test_nvidia_first5_profile_and_selected_manifest_are_pinned():
    profile = _validate_profile(PROFILE_DEFAULT)
    manifest = _select_manifest(profile, PROFILE_DEFAULT)
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


def test_nvidia_first5_uses_one_bounded_http_budget():
    profile = _validate_profile(PROFILE_DEFAULT)
    limits = profile["limits"]
    episode_calls = limits["max_steps"] * (1 + limits["invalid_retries"])
    # One /models probe, one compatibility completion, and five episodes.
    worst_case = 2 + 5 * episode_calls * (1 + limits["max_retries"])
    assert worst_case == 202
    assert worst_case <= limits["max_http_attempts"]
    assert Path(PROFILE_DEFAULT).is_file()
