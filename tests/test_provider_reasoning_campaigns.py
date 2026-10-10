from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.episode import EpisodeOptions, _complete_with_wire_api  # noqa: E402
from tools.atria_campaign import (  # noqa: E402
    _effective_campaign_job_seconds,
    _load_yaml,
    _validate_campaign_profile,
)
from tools.matched_fact_probe import load_profile, plan_from_profile, run_profile  # noqa: E402
from tools.run_suite import _build_command  # noqa: E402


class _WireRecorder:
    def __init__(self) -> None:
        self.chat_calls: list[dict] = []
        self.responses_calls: list[dict] = []
        self.result = object()

    def complete(self, **kwargs):
        self.chat_calls.append(kwargs)
        return self.result

    def complete_responses(self, input_text, **kwargs):
        self.responses_calls.append({"input_text": input_text, **kwargs})
        return self.result


def _options(provider: str, wire_api: str, *, effort: str | None = "high") -> EpisodeOptions:
    return EpisodeOptions(
        provider=provider,
        model="mercury-2.5" if provider == "mercury" else "Atria-Dawn-Preview",
        env="synthetic_env",
        difficulty="easy",
        wire_api=wire_api,
        reasoning_effort=effort,
        max_tokens=8192,
    )


def test_episode_threads_mercury_high_effort_as_flat_chat_field() -> None:
    client = _WireRecorder()
    messages = [{"role": "user", "content": "test"}]

    completion = _complete_with_wire_api(
        client,
        options=_options("mercury", "chat_completions"),
        messages=messages,
        request_extra={},
    )

    assert completion is client.result
    assert client.responses_calls == []
    call = client.chat_calls[0]
    assert call["model"] == "mercury-2.5"
    assert call["max_tokens"] == 8192
    assert call["request_extra"] == {"reasoning_effort": "high"}
    assert "reasoning" not in call["request_extra"]


def test_episode_threads_atria_effort_only_over_responses_surface() -> None:
    client = _WireRecorder()
    messages = [{"role": "user", "content": "test"}]

    completion = _complete_with_wire_api(
        client,
        options=_options("atria", "responses"),
        messages=messages,
        request_extra={},
    )

    assert completion is client.result
    assert client.chat_calls == []
    call = client.responses_calls[0]
    assert call["model"] == "Atria-Dawn-Preview"
    assert call["max_output_tokens"] == 8192
    assert call["reasoning_effort"] == "high"
    assert "reasoning" not in call


@pytest.mark.parametrize(
    "request_extra",
    [
        {"reasoning": {"effort": "high"}},
        {"reasoning_effort": "high"},
        {"reasoning_mode": "controlled_responses_reasoning_effort_high"},
    ],
)
def test_episode_refuses_ambiguous_reasoning_fields_in_atria_responses_request_extra(
    request_extra: dict,
) -> None:
    with pytest.raises(ValueError, match="explicit reasoning_effort"):
        _complete_with_wire_api(
            _WireRecorder(),
            options=_options("atria", "responses"),
            messages=[{"role": "user", "content": "test"}],
            request_extra=request_extra,
        )


def test_episode_rejects_a_flat_atria_responses_override_without_selected_effort() -> None:
    with pytest.raises(ValueError, match="explicit reasoning_effort"):
        _complete_with_wire_api(
            _WireRecorder(),
            options=_options("atria", "responses", effort=None),
            messages=[{"role": "user", "content": "test"}],
            request_extra={"reasoning_effort": "high"},
        )


def test_episode_refuses_to_guess_an_atria_chat_reasoning_equivalent() -> None:
    with pytest.raises(ValueError, match="only for Mercury"):
        _complete_with_wire_api(
            _WireRecorder(),
            options=_options("atria", "chat_completions"),
            messages=[{"role": "user", "content": "test"}],
            request_extra={},
        )


def test_suite_command_threads_wire_api_and_effort_as_episode_options(tmp_path: Path) -> None:
    case = {"environment": "synthetic_env", "difficulty": "easy", "seed": 4}
    base = dict(
        case=case,
        api_key_env="INCEPTION_API_KEY",
        secrets=None,
        api_base="https://api.inceptionlabs.ai/v1",
        sandbox="docker",
        output_dir=tmp_path,
        max_steps=1,
        max_tokens=8192,
        invalid_retries=0,
        keep_images=False,
        keep_workspace=False,
    )

    mercury = _build_command(
        provider="mercury", model="mercury-2.5", wire_api="chat_completions",
        reasoning_effort="high", **base,
    )
    assert mercury[mercury.index("--wire-api") + 1] == "chat_completions"
    assert mercury[mercury.index("--reasoning-effort") + 1] == "high"
    assert "--request-extra" not in mercury

    atria = _build_command(
        provider="atria", model="Atria-Dawn-Preview", api_key_env="ATRIA_API_KEY",
        api_base="https://api.atria-asi.ai/v1", wire_api="responses",
        reasoning_effort="high", **{key: value for key, value in base.items() if key not in {"api_key_env", "api_base"}},
    )
    assert atria[atria.index("--wire-api") + 1] == "responses"
    assert atria[atria.index("--reasoning-effort") + 1] == "high"
    assert "--request-extra" not in atria


def test_full_campaign_profiles_pin_provider_wire_and_separate_t1_contract() -> None:
    mercury = _load_yaml(ROOT / "experiments/mercury_covering_campaign.yaml")
    reasoning_atria = _load_yaml(ROOT / "experiments/reasoning_atria_covering_campaign.yaml")

    _validate_campaign_profile(mercury)
    _validate_campaign_profile(reasoning_atria)

    assert mercury["provider"] == "mercury"
    assert mercury["model"] == "mercury-2.5"
    assert mercury["api_key_env"] == "INCEPTION_API_KEY"
    assert mercury["wire_api"] == "chat_completions"
    assert mercury["reasoning_effort"] == "high"
    assert mercury["campaign_job_seconds"] == 19_800

    assert reasoning_atria["provider"] == "atria"
    assert reasoning_atria["wire_api"] == "responses"
    assert reasoning_atria["reasoning_effort"] == "high"
    assert reasoning_atria["campaign_job_seconds"] == 19_800
    assert "temperature" not in reasoning_atria
    assert "top_p" not in reasoning_atria

    contract = reasoning_atria["research_context"]["endpoint_contract"]
    assert contract["inquiry_regret"] == "not_measurable_single_turn"
    assert contract["recovery"] == "not_measurable_single_turn"
    assert contract["belief_correctness"] == "per_case_exact_posterior_match_not_calibration"
    assert contract["calibration_curve"] == "unavailable_no_population_metric"
    assert contract["aggregation"] == "separate_endpoint_channels_no_composite"


def test_invocation_wall_budget_can_only_reduce_the_profile_ceiling() -> None:
    assert _effective_campaign_job_seconds(6000, None) == 6000
    assert _effective_campaign_job_seconds(6000, 5940) == 5940
    with pytest.raises(ValueError, match="must not exceed"):
        _effective_campaign_job_seconds(6000, 6001)
    with pytest.raises(ValueError, match="at least 600"):
        _effective_campaign_job_seconds(6000, 599)


def test_campaign_profile_validation_rejects_cross_wire_reasoning_and_wrong_secret() -> None:
    mercury = _load_yaml(ROOT / "experiments/mercury_covering_campaign.yaml")
    wrong_secret = copy.deepcopy(mercury)
    wrong_secret["api_key_env"] = "MERCURY_API_KEY"
    with pytest.raises(ValueError, match="api_key_env"):
        _validate_campaign_profile(wrong_secret)

    reasoning_atria = _load_yaml(ROOT / "experiments/reasoning_atria_covering_campaign.yaml")
    wrong_wire = copy.deepcopy(reasoning_atria)
    wrong_wire["wire_api"] = "chat_completions"
    with pytest.raises(ValueError, match="Responses-API-only"):
        _validate_campaign_profile(wrong_wire)

    conflated_contract = copy.deepcopy(reasoning_atria)
    conflated_contract["research_context"]["endpoint_contract"]["calibration_curve"] = "belief_correctness"
    with pytest.raises(ValueError, match="calibration curve remains unavailable"):
        _validate_campaign_profile(conflated_contract)


def _workflow_example(path: str) -> dict:
    return yaml.load((ROOT / path).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize(
    ("profile_name", "provider", "model", "wire_api"),
    [
        ("t1_mercury.yaml", "mercury", "mercury-2.5", "chat_completions"),
        ("t1_reasoning_atria.yaml", "atria", "Atria-Dawn-Preview", "responses"),
    ],
)
def test_t1_profile_progress_and_reports_are_offline_testable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_name: str,
    provider: str, model: str, wire_api: str,
) -> None:
    import arena.providers
    import arena.secrets

    profile = load_profile(ROOT / "experiments" / profile_name)
    profile["matrix"] = {"n_facts": [3], "prior_world1": ["1/2"], "seeds": 1}
    target = profile["target"]
    target["max_tokens"] = 8192
    profile["budget"]["max_api_calls"] = 2
    calls: list[tuple[str, dict]] = []

    class _Completion:
        content = "not a structured answer"
        finish_reason = "stop"
        usage = {}

    class _FakeProviderClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def complete(self, **kwargs):
            calls.append(("chat", kwargs))
            return _Completion()

        def complete_responses(self, input_text, **kwargs):
            calls.append(("responses", {"input_text": input_text, **kwargs}))
            completion = _Completion()
            completion.finish_reason = "completed"
            return completion

    monkeypatch.setattr(
        arena.secrets,
        "resolve_provider",
        lambda *_args, **_kwargs: SimpleNamespace(api_key="offline-test", api_base="https://example.invalid/v1"),
    )
    monkeypatch.setattr(arena.providers, "ProviderClient", _FakeProviderClient)
    out = tmp_path / "t1.json"
    report = run_profile(profile, out=str(out), progress_dir=str(tmp_path / "progress"))

    assert len(calls) == 2
    assert all(call[0] == ("responses" if wire_api == "responses" else "chat") for call in calls)
    assert report["target"]["provider"] == provider
    assert report["target"]["model"] == model
    assert report["target"]["api_base"] == target["api_base"]
    assert report["target"]["wire_api"] == wire_api
    assert report["target"]["reasoning_effort"] == "high"
    assert target["max_tokens"] == 8192
    token_field = "max_output_tokens" if wire_api == "responses" else "max_tokens"
    assert all(call[1][token_field] == 8192 for call in calls)
    assert report["measurement_contract"]["inquiry_regret"] == "not_measurable"
    assert report["measurement_contract"]["recovery"] == "not_measurable"
    assert report["measurement_contract"]["calibration_curve"] == "unavailable_no_population_metric"
    assert out.is_file()
    assert not (tmp_path / "progress" / "t1_partial.json").exists()
    progress = yaml.safe_load((tmp_path / "progress" / "campaign_progress.json").read_text())
    assert progress["phase"] == "T1 complete"
    assert progress["t1_api_calls_completed"] == 2


@pytest.mark.parametrize(
    ("profile_name", "provider", "model", "wire_api", "secret"),
    [
        ("t1_mercury.yaml", "mercury", "mercury-2.5", "chat_completions", "INCEPTION_API_KEY"),
        ("t1_reasoning_atria.yaml", "atria", "Atria-Dawn-Preview", "responses", "ATRIA_API_KEY"),
    ],
)
def test_t1_plans_keep_target_and_reasoning_identity_explicit(
    profile_name: str, provider: str, model: str, wire_api: str, secret: str,
) -> None:
    profile = load_profile(ROOT / "experiments" / profile_name)
    plan = plan_from_profile(profile)

    assert plan["provider"] == provider
    assert plan["model"] == model
    assert plan["api_base"] == load_profile(ROOT / "experiments" / profile_name)["target"]["api_base"]
    assert plan["wire_api"] == wire_api
    assert plan["reasoning_effort"] == "high"
    assert plan["max_tokens"] == 8192
    assert plan["planned_api_calls"] == 72
    assert plan["within_budget"] is True
    assert profile["matrix"]["seeds"] == 6
    assert profile["budget"]["max_api_calls"] == 72
    oversized_profile = copy.deepcopy(profile)
    oversized_profile["matrix"]["seeds"] = 24
    oversized_plan = plan_from_profile(oversized_profile)
    assert oversized_plan["planned_api_calls"] == 288
    assert oversized_plan["within_budget"] is False
    assert profile["target"]["api_key_env"] == secret


def test_manual_copy_workflows_keep_issue_identity_and_secrets_distinct() -> None:
    mercury = _workflow_example("docs/workflows/mercury-covering-campaign.yml.example")
    atria = _workflow_example("docs/workflows/reasoning-atria-covering-campaign.yml.example")

    assert mercury["name"] == "Mercury covering campaign"
    assert atria["name"] == "Reasoning-Atria covering campaign"
    # Mercury's gate must be able to finish one 108-minute atomic row after a
    # worst-case 70-minute T1 probe. Reasoning-Atria retains its shorter tick.
    assert mercury["jobs"]["campaign"]["timeout-minutes"] == "350"
    assert atria["jobs"]["campaign"]["timeout-minutes"] == "115"
    mercury_run_step = next(step for step in mercury["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Run T1"))
    atria_run_step = next(step for step in atria["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Run T1"))
    assert mercury_run_step["timeout-minutes"] == "330"
    assert atria_run_step["timeout-minutes"] == "100"
    mercury_run = mercury_run_step["run"]
    atria_run = atria_run_step["run"]
    assert "--label \"Mercury covering campaign\"" in mercury_run
    assert "experiments/mercury_covering_status_issue.txt" in mercury_run
    assert "set -euo pipefail" in mercury_run
    assert "4200s" in mercury_run
    assert "CAMPAIGN_SECONDS=$((19800 - ELAPSED_SECONDS - 60))" in mercury_run
    mercury_profile = load_profile(ROOT / "experiments/mercury_covering_campaign.yaml")
    assert int(mercury_run_step["timeout-minutes"]) * 60 == mercury_profile["campaign_job_seconds"]
    assert mercury_profile["campaign_job_seconds"] - 4200 - 60 >= 6480
    assert "--job-seconds" in mercury_run
    assert '"$OUT/t1_interrupted.json"' in mercury_run
    mercury_restore = next(
        step["run"] for step in mercury["jobs"]["campaign"]["steps"] if step.get("name") == "Restore or initialize campaign output"
    )
    assert 'git rev-parse HEAD > "$OUT/campaign_ref.txt"' in mercury_restore
    mercury_env = next(
        step["env"] for step in mercury["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Run T1")
    )
    assert mercury_env["INCEPTION_API_KEY"] == "${{ secrets.INCEPTION_API_KEY }}"
    assert "--label \"Reasoning-Atria covering campaign\"" in atria_run
    assert "experiments/reasoning_atria_covering_status_issue.txt" in atria_run
    assert "set -euo pipefail" in atria_run
    assert "4200s" in atria_run
    assert "CAMPAIGN_SECONDS=$((6000 - ELAPSED_SECONDS - 60))" in atria_run
    assert "--job-seconds" in atria_run
    assert '"$OUT/t1_interrupted.json"' in atria_run
    atria_restore = next(
        step["run"] for step in atria["jobs"]["campaign"]["steps"] if step.get("name") == "Restore or initialize campaign output"
    )
    assert 'git rev-parse HEAD > "$OUT/campaign_ref.txt"' in atria_restore
    atria_env = next(
        step["env"] for step in atria["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Run T1")
    )
    assert atria_env["ATRIA_API_KEY"] == "${{ secrets.ATRIA_API_KEY }}"
    assert "MERCURY_API_KEY" not in mercury_run
    assert "expected_provider=\"atria\"" in next(
        step["run"] for step in atria["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Decide")
    )
    assert mercury["concurrency"]["group"] != atria["concurrency"]["group"]

    mercury_t1 = _workflow_example("docs/workflows/mercury-t1-campaign.yml.example")
    atria_t1 = _workflow_example("docs/workflows/reasoning-atria-t1-campaign.yml.example")
    assert mercury_t1["on"]["workflow_dispatch"]["inputs"]["ref"]["default"] == "main"
    assert atria_t1["on"]["workflow_dispatch"]["inputs"]["ref"]["default"] == "main"
