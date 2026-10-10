from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
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
    _compatibility_check,
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
    # The reasoning campaigns now advertise a 19,800-second ceiling, and the
    # clamp is what stops a resume from ever being handed a wall budget that
    # cannot fit one atomic gate row (6,480 seconds worst case).
    assert _effective_campaign_job_seconds(19_800, None) == 19_800
    assert _effective_campaign_job_seconds(19_800, 19_740) == 19_740
    # Worst case inside a live step: a full 70-minute T1 probe, the one-minute
    # cleanup reserve, then the controller's 900-second state-upload reserve.
    # What is left for the gate must still fit one atomic gate row.
    assert 19_800 - 4_200 - 60 - 900 >= 6_480
    # The same arithmetic under the old ceiling is what refused to start a row.
    assert 6_000 - 4_200 - 60 - 900 < 6_480
    with pytest.raises(ValueError, match="must not exceed"):
        _effective_campaign_job_seconds(19_800, 19_801)
    with pytest.raises(ValueError, match="at least 600"):
        _effective_campaign_job_seconds(19_800, 599)


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
    # Both reasoning campaigns must be able to finish one 108-minute atomic
    # gate row after a worst-case 70-minute T1 probe.
    assert mercury["jobs"]["campaign"]["timeout-minutes"] == "350"
    assert atria["jobs"]["campaign"]["timeout-minutes"] == "350"
    mercury_run_step = next(step for step in mercury["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Run T1"))
    atria_run_step = next(step for step in atria["jobs"]["campaign"]["steps"] if step.get("name", "").startswith("Run T1"))
    assert mercury_run_step["timeout-minutes"] == "330"
    assert atria_run_step["timeout-minutes"] == "330"
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
    assert "CAMPAIGN_SECONDS=$((19800 - ELAPSED_SECONDS - 60))" in atria_run
    atria_profile = load_profile(ROOT / "experiments/reasoning_atria_covering_campaign.yaml")
    assert int(atria_run_step["timeout-minutes"]) * 60 == atria_profile["campaign_job_seconds"]
    assert atria_profile["campaign_job_seconds"] - 4200 - 60 >= 6480
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
    for workflow in (mercury, atria):
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        assert inputs["resume_previous"] == {
            "description": "Resume the latest campaign-state artifact instead of starting fresh",
            "required": "true",
            "type": "boolean",
            "default": "true",
        }
        decide = next(
            step["run"] for step in workflow["jobs"]["campaign"]["steps"]
            if step.get("name", "").startswith("Decide")
        )
        assert 'inputs.resume_previous' in decide
        assert '!= "true"' in decide
        assert "explicit fresh manual dispatch" in decide

    mercury_t1 = _workflow_example("docs/workflows/mercury-t1-campaign.yml.example")
    atria_t1 = _workflow_example("docs/workflows/reasoning-atria-t1-campaign.yml.example")
    assert mercury_t1["on"]["workflow_dispatch"]["inputs"]["ref"]["default"] == "main"
    assert atria_t1["on"]["workflow_dispatch"]["inputs"]["ref"]["default"] == "main"


def _workflow_pair(workflow_name: str) -> tuple[dict, dict]:
    """Return the live Actions workflow and its documented manual copy."""
    deployed = yaml.load(
        (ROOT / ".github" / "workflows" / f"{workflow_name}.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    return deployed, _workflow_example(f"docs/workflows/{workflow_name}.yml.example")


def _fresh_dispatch_guard(decide_run: str) -> str:
    """Slice out just the fresh-versus-resume guard of a Decide step."""
    lines = decide_run.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line.strip().startswith('if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]')
    )
    end = next(index for index in range(start, len(lines)) if lines[index].strip() == "exit 0")
    return "\n".join([*lines[start : end + 1], "fi"])


@pytest.mark.parametrize(
    ("workflow_name", "campaign_label", "profile_path"),
    [
        (
            "mercury-covering-campaign",
            "Mercury",
            "experiments/mercury_covering_campaign.yaml",
        ),
        (
            "reasoning-atria-covering-campaign",
            "Reasoning-Atria",
            "experiments/reasoning_atria_covering_campaign.yaml",
        ),
    ],
)
def test_deployed_and_documented_covering_workflows_share_the_wall_budget(
    workflow_name: str, campaign_label: str, profile_path: str
) -> None:
    """The live workflow and its manual-copy example must never drift apart.

    A previous session left the two halves of this pair disagreeing: one side
    carried the 350/330-minute budgets while the other still carried 115/100.
    The budgets exist because one worst-case atomic gate row needs 6,480
    seconds, which the old effective ~6,000-second controller budget could
    never start (it refused with "5000s remaining, 6480s required"). Half of
    an upgrade is a silent downgrade on the other file's campaign path.
    """
    deployed, documented = _workflow_pair(workflow_name)
    assert deployed == documented
    profile = load_profile(ROOT / profile_path)

    for workflow in (deployed, documented):
        assert workflow["jobs"]["campaign"]["timeout-minutes"] == "350"
        run_step = next(
            step
            for step in workflow["jobs"]["campaign"]["steps"]
            if step.get("name", "").startswith("Run T1")
        )
        run = run_step["run"]
        assert int(run_step["timeout-minutes"]) == 330
        assert int(run_step["timeout-minutes"]) * 60 == profile["campaign_job_seconds"]
        assert "CAMPAIGN_SECONDS=$((19800 - ELAPSED_SECONDS - 60))" in run
        # The profile clamp survives the larger ceiling, so a late tick can
        # never be handed more wall time than the profile advertises.
        assert 'if [ "$CAMPAIGN_SECONDS" -gt "$MAX_CAMPAIGN_SECONDS" ]; then' in run
        assert "CAMPAIGN_SECONDS=$MAX_CAMPAIGN_SECONDS" in run
        assert f'{campaign_label} campaign budget: elapsed=${{ELAPSED_SECONDS}}s' in run
        assert "profile_max=${MAX_CAMPAIGN_SECONDS}s effective=${CAMPAIGN_SECONDS}s" in run
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        assert inputs["resume_previous"] == {
            "description": "Resume the latest campaign-state artifact instead of starting fresh",
            "required": "true",
            "type": "boolean",
            "default": "true",
        }


@pytest.mark.parametrize(
    "workflow_name",
    ["mercury-covering-campaign", "reasoning-atria-covering-campaign"],
)
@pytest.mark.parametrize(
    ("event_name", "resume_previous", "expects_fresh"),
    [
        ("workflow_dispatch", "true", False),
        ("workflow_dispatch", "false", True),
        ("schedule", "", False),
        ("schedule", "true", False),
        ("push", "", False),
    ],
)
def test_resume_checkbox_is_decided_by_the_real_guard_script(
    tmp_path: Path,
    workflow_name: str,
    event_name: str,
    resume_previous: str,
    expects_fresh: bool,
) -> None:
    """Execute the Decide guard instead of grepping it.

    Only an explicit manual dispatch with the checkbox unchecked may start a new
    lineage. A checked dispatch and every scheduled tick must fall through to
    the latest-artifact supervisor path, which is what restores an already
    completed T1 (and its gate rows) rather than paying for it a second time.
    """
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - ubuntu runners always ship bash
        pytest.skip("bash is required to exercise the Decide guard")
    _deployed, documented = _workflow_pair(workflow_name)
    decide = next(
        step["run"]
        for step in documented["jobs"]["campaign"]["steps"]
        if step.get("name", "").startswith("Decide")
    )
    assert "inputs.resume_previous" in decide  # the slice really is the checkbox branch
    guard = (
        _fresh_dispatch_guard(decide)
        .replace('"${{ inputs.resume_previous }}"', '"$RESUME_PREVIOUS"')
        .replace("${{ inputs.ref }}", "PINNED-REF")
        .replace("${{ inputs.execution_mode }}", "paid")
    )
    assert '"$RESUME_PREVIOUS"' in guard
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    script = "set -euo pipefail\n" + guard + '\necho "fell-through-to-resume" >> "$GITHUB_OUTPUT"\n'
    completed = subprocess.run(
        [bash, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_OUTPUT": str(output),
            "RESUME_PREVIOUS": resume_previous,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    recorded = output.read_text(encoding="utf-8")
    if expects_fresh:
        assert "mode=fresh" in recorded
        assert "reason=explicit fresh manual dispatch" in recorded
        # A fresh dispatch may never claim the resume path's marker.
        assert "fell-through-to-resume" not in recorded
    else:
        assert "mode=fresh" not in recorded
        assert "fell-through-to-resume" in recorded


class _ProbeOpener:
    """Answer the probe with canned provider bodies, offline.

    The real ``ProviderClient`` still builds the request, so its keyword-only
    signatures are enforced and the recorded payload shows the field name that
    actually goes on the wire.
    """

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def __call__(self, req, timeout=None):  # noqa: ANN001, ANN204
        payload = json.loads(req.data.decode("utf-8"))
        self.payloads.append(payload)
        if str(req.full_url).endswith("/responses"):
            body = {
                "id": "resp_probe",
                "model": payload["model"],
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [{"text": "thinking" * 40}]},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "READY"}],
                    },
                ],
                "usage": {"input_tokens": 11, "output_tokens": 8_150},
            }
        else:
            body = {
                "model": payload["model"],
                "choices": [
                    {"message": {"role": "assistant", "content": "READY"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 8_150},
            }
        return _ProbeResponse(body)


class _ProbeResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_ProbeResponse":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


@pytest.mark.parametrize(
    ("profile_path", "wire_api", "size_key"),
    [
        ("experiments/mercury_covering_campaign.yaml", "chat_completions", "max_completion_tokens"),
        ("experiments/reasoning_atria_covering_campaign.yaml", "responses", "max_output_tokens"),
    ],
)
def test_compatibility_probe_sends_profile_token_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_path: str, wire_api: str, size_key: str
) -> None:
    """The READY probe must request the profile ceiling under the right keyword.

    Two separate live failures are pinned here. A hard-coded 128-token probe was
    swallowed whole by Mercury's hidden reasoning (``finish_reason: length``, no
    visible text), so the ceiling must come from ``limits.max_tokens``. And the
    two wire surfaces name the size field differently while both methods are
    keyword-only, so passing ``max_output_tokens`` to ``complete()`` is not a
    no-op: it raises TypeError before any request is sent.
    """
    import arena.providers as providers

    profile = load_profile(ROOT / profile_path)
    assert str(profile["wire_api"]) == wire_api
    ceiling = int(profile["limits"]["max_tokens"])
    assert ceiling == 8_192

    opener = _ProbeOpener()

    class _ProbedClient(providers.ProviderClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["opener"] = opener
            kwargs["sleep"] = lambda _seconds: None
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("tools.atria_campaign.ProviderClient", _ProbedClient)
    credentials = SimpleNamespace(api_key="compat-probe-key", api_base=profile["api_base"])

    result = _compatibility_check(profile, credentials, tmp_path)

    assert result["status"] == "passed", result
    assert result["effective_request"]["wire_api"] == wire_api
    assert result["effective_request"]["max_output_tokens"] == ceiling
    assert result["effective_request"]["max_output_tokens"] != 128
    payload = opener.payloads[0]
    assert payload[size_key] == ceiling
    # Exactly one completion-size field per wire: the sibling names must never
    # leak into the other endpoint's request body.
    foreign_size_keys = {"max_tokens", "max_output_tokens", "max_completion_tokens"} - {size_key}
    assert foreign_size_keys.isdisjoint(payload)
    if wire_api == "responses":
        assert payload["reasoning"] == {"effort": "high"}
    else:
        assert payload["reasoning_effort"] == "high"
    assert json.loads((tmp_path / "compatibility.json").read_text(encoding="utf-8"))
    assert "compat-probe-key" not in (tmp_path / "compatibility.json").read_text(encoding="utf-8")


def test_provider_client_token_keywords_are_wire_specific() -> None:
    """Guard the exact TypeError that killed the first manual Mercury attempt."""
    import inspect

    import arena.providers as providers

    chat = inspect.signature(providers.ProviderClient.complete).parameters
    responses = inspect.signature(providers.ProviderClient.complete_responses).parameters
    assert "max_tokens" in chat
    assert "max_output_tokens" not in chat
    assert "max_output_tokens" in responses
    assert responses["max_output_tokens"].kind is inspect.Parameter.KEYWORD_ONLY
