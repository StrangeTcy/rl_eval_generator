"""Tests for the provider/environment feasibility probe.

The probe exists to answer a question before money is spent, so these tests hold
it to two standards: the offline half has to be right about this repository's own
six environments, and no stage may put a credential, an endpoint, or a guessed
host into its output.
"""
from __future__ import annotations

import json
import re
import sys
from urllib import error
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.providers import Completion, ProviderError  # noqa: E402
from tools import provider_env_preflight as probe  # noqa: E402
from tools.provider_preflight import probe_provider  # noqa: E402

FAKE_KEY = "ar-fake-key-do-not-leak-0123456789"
SIX = {
    "rd_adaptive_halting",
    "rd_gradient_credit",
    "rd_state_carry",
    "sheaf_invariant_gluing",
    "sheaf_physical_constraints",
    "sheaf_schema_sync",
}


def _stage(report: dict[str, Any], name: str) -> dict[str, Any]:
    for stage in report["stages"]:
        if stage["stage"] == name:
            return stage
    raise AssertionError(f"stage {name} missing from the report")


def _completion(content: str, finish_reason: str = "stop", reasoning: int | None = None) -> Completion:
    return Completion(
        content=content,
        requested_model="astra-probe",
        resolved_model="astra-probe",
        finish_reason=finish_reason,
        usage={"total_tokens": 12},
        raw_response={},
        latency_ms=7,
        request_id="req-1",
        response_headers={},
        status_code=200,
        reasoning_content_length=reasoning,
    )


class _FakeClient:
    """Stands in for ProviderClient so the wire stage can be tested unpaid."""

    def __init__(self, completion: Completion) -> None:
        self.completion = completion
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> Completion:
        self.calls.append(kwargs)
        return self.completion


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def test_the_six_environments_are_found_by_directory_not_by_a_hardcoded_list() -> None:
    wanted = probe.selected_environments(ROOT)
    assert set(wanted["environments"]) == SIX
    assert wanted["names_not_in_registry"] == []


def test_a_requested_name_that_is_not_in_the_registry_is_reported_not_dropped() -> None:
    wanted = probe.selected_environments(ROOT, env_dirs=(), explicit=("sheaf_schema_sync", "sheaf_typo"))
    assert set(wanted["environments"]) == {"sheaf_schema_sync"}
    assert wanted["names_not_in_registry"] == ["sheaf_typo"]


# ---------------------------------------------------------------------------
# credential
# ---------------------------------------------------------------------------


def test_an_unmodelled_provider_travels_as_custom_and_says_so() -> None:
    stage = probe.stage_credential(
        "agentrouter",
        key_envs=("AGENTROUTER_API_KEY",),
        base_envs=("AGENTROUTER_API_BASE",),
        api_base="https://router.example.invalid/v1",
        secret_path=None,
        environ={"AGENTROUTER_API_KEY": FAKE_KEY},
    )
    assert stage["status"] == "ready"
    assert stage["modelled_provider"] is False
    assert stage["wire_provider"] == "custom"
    assert stage["key_source"] == "env:AGENTROUTER_API_KEY"
    # The endpoint is reduced to its host: the base URL never reaches an artifact.
    assert stage["api_base_host"] == "router.example.invalid"
    assert "https://router.example.invalid/v1" not in json.dumps(stage)
    assert FAKE_KEY not in json.dumps(stage)
    assert any("not a modelled provider" in note for note in stage["notes"])


def test_the_existing_preflight_cannot_answer_this_question_at_all() -> None:
    """`provider_preflight` flattens an unknown provider into 'credential_error'.

    That is the gap this tool exists for: with a key present and resolvable, the
    old probe still reports the same line it reports when there is no key.
    """

    old = probe_provider("agentrouter", secret_path=None, timeout=1.0)
    assert old["status"] == "credential_error"
    new = probe.stage_credential(
        "agentrouter",
        key_envs=("AGENTROUTER_API_KEY",),
        base_envs=(),
        api_base="https://router.example.invalid/v1",
        secret_path=None,
        environ={"AGENTROUTER_API_KEY": FAKE_KEY},
    )
    assert new["status"] == "ready"


def test_a_key_that_only_exists_as_an_actions_secret_is_named_as_such() -> None:
    stage = probe.stage_credential(
        "agentrouter",
        key_envs=("AGENTROUTER_API_KEY",),
        base_envs=("AGENTROUTER_API_BASE",),
        api_base=None,
        secret_path=None,
        environ={},
    )
    assert stage["status"] == "key_not_visible_here"
    assert stage["key_source"] is None
    # The endpoint is documented, so it resolves; the key is the missing half.
    assert stage["api_base_source"] == "documented_default"
    assert any("Actions secret" in blocker for blocker in stage["blockers"])


def test_no_endpoint_is_ever_guessed() -> None:
    """A provider nobody documented gets no default, however plausible its name."""

    stage = probe.stage_credential(
        "workbuddy",
        key_envs=("WORKBUDDY_API_KEY",),
        base_envs=("WORKBUDDY_API_BASE",),
        api_base=None,
        secret_path=None,
        environ={"WORKBUDDY_API_KEY": FAKE_KEY},
    )
    assert stage["status"] == "endpoint_not_declared"
    assert stage["api_base_host"] is None
    assert stage["api_base_source"] is None
    assert any("none will be guessed" in blocker for blocker in stage["blockers"])


def test_a_documented_endpoint_is_used_as_a_default_and_carries_its_citation() -> None:
    stage = probe.stage_credential(
        "agentrouter",
        key_envs=("AGENTROUTER_API_KEY",),
        base_envs=("AGENTROUTER_API_BASE",),
        api_base=None,
        secret_path=None,
        environ={"AGENTROUTER_API_KEY": FAKE_KEY},
    )
    base, citation = probe.DOCUMENTED_BASES["agentrouter"]
    assert stage["status"] == "ready"
    assert stage["api_base_source"] == "documented_default"
    assert stage["api_base_host"] == "agentrouter.org"
    assert stage["api_base_documented_source"] == citation
    # The OpenAI-compatible wire is the base with /v1; the bare host is Anthropic's.
    assert base.endswith("/v1")
    assert any("documented base is not a guessed one" in note for note in stage["notes"])
    assert any("503" in note and "gpt-6-astra" in note for note in stage["notes"])
    assert base not in json.dumps({k: v for k, v in stage.items() if k != "notes"})


def test_using_the_anthropic_wire_form_for_an_openai_client_is_flagged() -> None:
    stage = probe.stage_credential(
        "agentrouter",
        key_envs=("AGENTROUTER_API_KEY",),
        base_envs=(),
        api_base="https://agentrouter.org",
        secret_path=None,
        environ={"AGENTROUTER_API_KEY": FAKE_KEY},
    )
    assert stage["api_base_source"] == "cli"
    assert any("does not carry the /v1 path" in note for note in stage["notes"])


def test_the_key_environment_variables_are_tried_in_order() -> None:
    stage = probe.stage_credential(
        "agentrouter",
        key_envs=("AGENTROUTER_API_KEY", "AGENT_ROUTER_API_KEY"),
        base_envs=("AGENTROUTER_API_BASE",),
        api_base=None,
        secret_path=None,
        environ={"AGENT_ROUTER_API_KEY": FAKE_KEY, "AGENTROUTER_API_BASE": "https://b.example.invalid/v1"},
    )
    assert stage["key_source"] == "env:AGENT_ROUTER_API_KEY"
    assert stage["api_base_host"] == "b.example.invalid"
    assert stage["status"] == "ready"


# ---------------------------------------------------------------------------
# judge stack
# ---------------------------------------------------------------------------


def test_pip_packages_survives_the_dockerfiles_continuation_lines() -> None:
    text = (ROOT / "shared" / "Dockerfile.judge").read_text(encoding="utf-8")
    packages = probe._pip_packages(text)
    assert {"torch", "torchvision", "PIL", "pytest"} <= packages
    # `RUN` is an instruction and a wheel index is a URL; neither is a package.
    assert "run" not in packages
    assert not any("://" in name or "pytorch" in name for name in packages)


def test_the_judge_image_provides_what_the_six_judges_import() -> None:
    provides = probe._image_provides(ROOT, probe._JUDGE_DOCKERFILE)
    assert {"torch", "judge_lib", "patch_validator", "source_validator"} <= provides


def test_judge_imports_are_read_from_a_generated_instance_not_from_a_template() -> None:
    """Templates carry %%PLACEHOLDER%% tokens, so they are not parseable Python."""

    template = ROOT / "envs" / "cat_theo" / "sheaf" / "sheaf_schema_sync" / "files" / "judge.py"
    with pytest.raises(SyntaxError):
        compile(template.read_text(encoding="utf-8"), str(template), "exec")

    case = {
        "environment": "sheaf_schema_sync",
        "difficulty_levels": {"naming": "easy", "symptom_mask": "easy"},
        "seed": 0,
    }
    generated = probe._generate_instance(ROOT, case)
    assert generated is not None
    try:
        imports = probe._judge_imports(ROOT, {"sheaf_schema_sync": generated})
    finally:
        import shutil

        shutil.rmtree(generated, ignore_errors=True)
        for path in ROOT.glob("provider-env-preflight-*"):
            shutil.rmtree(path, ignore_errors=True)
    entry = imports["sheaf_schema_sync"]
    assert entry["status"] == "imports_satisfied", entry
    assert entry["missing_imports"] == []
    assert "torch" in entry["imports"]


def test_a_judge_import_the_image_does_not_install_is_a_hard_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "_image_provides", lambda root, dockerfile: {"pytest"})
    manifest = probe.build_manifest(root=ROOT, matrix="representative", seeds=[0], dry_run=True)
    cases = [case for case in manifest["cases"] if case["environment"] == "rd_state_carry"]
    assert cases, "the manifest has to carry the environment this test is about"
    stage = probe.stage_judge_stack(
        ROOT,
        {"rd_state_carry": "envs/recurrent_depth/state_carry/config.yaml"},
        {"rd_state_carry": cases},
        check_docker=False,
        timeout=20.0,
    )
    assert stage["judge_imports_unchecked"] == []
    assert stage["status"] == "blocked"
    assert stage["hard_blocker"] is True
    assert any("torch" in blocker and "fail at grading" in blocker for blocker in stage["blockers"])


def test_an_environment_that_cannot_be_generated_is_named_as_unchecked() -> None:
    stage = probe.stage_judge_stack(
        ROOT,
        {"rd_state_carry": "envs/recurrent_depth/state_carry/config.yaml"},
        {"rd_state_carry": []},
        check_docker=False,
        timeout=20.0,
    )
    assert stage["judge_imports_unchecked"] == ["rd_state_carry"]
    assert any("were not read" in note for note in stage["notes"])


def test_ci_is_credited_with_the_judge_stack_this_host_lacks() -> None:
    steps = probe._ci_judge_stack_steps(ROOT)
    by_workflow = {entry["workflow"]: entry for entry in steps}
    assert "mercury-pairwise-campaign.yml" in by_workflow
    assert any("judge stack" in name for name in by_workflow["mercury-pairwise-campaign.yml"]["steps"])
    assert by_workflow["mercury-pairwise-campaign.yml"]["pins"]["torch"] == "2.5.1"


# ---------------------------------------------------------------------------
# gate status
# ---------------------------------------------------------------------------


def test_only_one_of_the_six_can_produce_a_gated_verdict() -> None:
    wanted = probe.selected_environments(ROOT)
    stage = probe.stage_gate_status(ROOT, wanted["environments"])
    assert stage["environments"]["rd_state_carry"]["graded_by"] == "exact_instance_gate"
    assert stage["environments"]["rd_state_carry"]["exact_instance_reference"] == "hidden_depth_exact"
    assert set(stage["compile_only"]) == SIX - {"rd_state_carry"}
    assert any("scoreboard row" in note for note in stage["notes"])
    for entry in stage["environments"].values():
        assert entry["verdict_relevant_files"], "every one of these envs is inside the gate closure"


# ---------------------------------------------------------------------------
# wire
# ---------------------------------------------------------------------------


def test_the_wire_stage_accepts_only_an_answer_the_episode_loop_can_use() -> None:
    client = _FakeClient(_completion('{"type": "list_files", "path": "."}'))
    stage = probe.stage_wire(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model="astra-probe",
        max_tokens=96,
        timeout=5.0,
        client_factory=lambda: client,
    )
    assert stage["status"] == "ok"
    assert stage["action_parsed"] is True
    assert stage["action_type"] == "list_files"
    assert stage["blockers"] == []
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["max_tokens"] == 96
    assert FAKE_KEY not in json.dumps(stage)


def test_prose_is_a_failure_even_though_it_is_http_200() -> None:
    client = _FakeClient(_completion("Sure! Let me start by listing the files in the workspace."))
    stage = probe.stage_wire(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model="astra-probe",
        max_tokens=96,
        timeout=5.0,
        client_factory=lambda: client,
    )
    assert stage["status"] == "unusable"
    assert stage["hard_blocker"] is True
    assert any("did not parse as an action" in blocker for blocker in stage["blockers"])


def test_a_truncated_completion_names_the_knob_that_would_fix_it() -> None:
    client = _FakeClient(_completion('{"type": "apply_patch", "patch": "diff ', finish_reason="length"))
    stage = probe.stage_wire(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model="astra-probe",
        max_tokens=96,
        timeout=5.0,
        client_factory=lambda: client,
    )
    assert stage["status"] == "unusable"
    assert any("max_tokens=96" in blocker for blocker in stage["blockers"])


def test_a_reasoning_channel_the_controller_would_ignore_is_reported_as_waste() -> None:
    client = _FakeClient(_completion('{"cmd": "ls"}', reasoning=4096))
    stage = probe.stage_wire(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model="astra-probe",
        max_tokens=96,
        timeout=5.0,
        client_factory=lambda: client,
    )
    assert stage["reasoning_content_length"] == 4096
    assert any("billed and ignored" in note for note in stage["notes"])


def test_the_wire_stage_spends_one_attempt_with_no_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, Any] = {}
    client = _FakeClient(_completion('{"cmd": "ls"}'))

    def fake_client(provider: str, api_key: str, **kwargs: Any) -> _FakeClient:
        built.update({"provider": provider, "api_key": api_key, **kwargs})
        return client

    monkeypatch.setattr(probe, "ProviderClient", fake_client)
    stage = probe.stage_wire(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model="astra-probe",
        max_tokens=96,
        timeout=5.0,
    )
    assert stage["status"] == "ok"
    assert built["max_retries"] == 0
    assert built["max_http_attempts"] == 1
    assert built["api_key"] == FAKE_KEY
    assert len(client.calls) == 1


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = {"X-Request-Id": "req-9"}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_the_catalog_stage_finds_the_model_the_filter_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"data": [{"id": "astra-1"}, {"id": "astra-2-mini"}, {"id": "some-other"}]})
    monkeypatch.setattr(probe, "open_no_redirect", lambda req, timeout: _FakeResponse(body))
    stage = probe.stage_catalog(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model_filter="astra",
        timeout=5.0,
    )
    assert stage["status"] == "reachable"
    assert stage["model_count"] == 3
    assert stage["matched_models"] == ["astra-1", "astra-2-mini"]
    assert stage["request_id"] == "req-9"
    assert FAKE_KEY not in json.dumps(stage)


def test_a_roster_without_the_model_is_a_blocker_that_shows_the_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"data": [{"id": "something-else"}]})
    monkeypatch.setattr(probe, "open_no_redirect", lambda req, timeout: _FakeResponse(body))
    stage = probe.stage_catalog(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model_filter="astra",
        timeout=5.0,
    )
    assert stage["status"] == "model_not_in_catalog"
    assert stage["hard_blocker"] is True
    assert stage["model_ids_sample"] == ["something-else"]


def test_a_200_with_no_model_ids_means_the_endpoint_is_not_a_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "open_no_redirect", lambda req, timeout: _FakeResponse("{\"ok\":true}"))
    stage = probe.stage_catalog(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model_filter="astra",
        timeout=5.0,
    )
    assert stage["status"] == "empty_roster"
    assert any("adapter" in blocker for blocker in stage["blockers"])


def test_a_plaintext_base_is_refused_before_any_key_is_sent() -> None:
    stage = probe.stage_catalog(
        provider="agentrouter",
        wire_provider="custom",
        api_base="http://router.example.invalid/v1",
        api_key=FAKE_KEY,
        model_filter="astra",
        timeout=5.0,
    )
    assert stage["status"] == "request_error"
    assert stage["hard_blocker"] is True
    assert FAKE_KEY not in json.dumps(stage)


# ---------------------------------------------------------------------------
# whole-report behaviour
# ---------------------------------------------------------------------------


def test_the_offline_report_from_a_workstation_says_what_only_ci_can_answer() -> None:
    report = probe.run_preflight(
        root=ROOT,
        env_dirs=(),
        env_names=("sheaf_schema_sync",),
        stage="offline",
        matrices=("representative",),
        environ={},
    )
    assert report["verdict"]["verdict"] == "unknown_needs_ci"
    assert report["verdict"]["hard_blockers"] == []
    assert _stage(report, "env_build")["status"] == "ready"
    assert _stage(report, "judge_stack")["status"] in {"ready", "host_limited"}
    assert "run the offline stages in CI" in report["verdict"]["next_step"]


def test_a_report_never_carries_the_key_even_when_every_stage_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"data": [{"id": "astra-probe"}, {"id": "unrelated"}]})
    monkeypatch.setattr(probe, "open_no_redirect", lambda req, timeout: _FakeResponse(body))
    report = probe.run_preflight(
        root=ROOT,
        env_dirs=(),
        env_names=("rd_state_carry",),
        stage="all",
        matrices=("representative",),
        api_base="https://router.example.invalid/v1",
        environ={"AGENTROUTER_API_KEY": FAKE_KEY},
        client_factory=lambda: _FakeClient(_completion('{"cmd": "ls"}')),
    )
    serialized = json.dumps(report)
    assert FAKE_KEY not in serialized
    # The host is reported, the endpoint is not: provider_preflight's output
    # contract forbids endpoints, and a report gets pasted into issues.
    assert "router.example.invalid/v1" not in serialized
    assert _stage(report, "credential")["api_base_host"] == "router.example.invalid"
    assert "<api-base>" in _stage(report, "plan")["commands"]["one_case_rehearsal"]
    # The wire stage probes the model the catalog matched, not one someone typed.
    assert _stage(report, "catalog")["matched_models"] == ["astra-probe"]
    assert _stage(report, "wire")["status"] == "ok"
    assert _stage(report, "wire")["model_requested"] == "astra-probe"
    assert report["verdict"]["verdict"] in {"possible", "possible_with_gaps"}


def test_the_rehearsal_command_names_the_variable_holding_the_endpoint() -> None:
    report = probe.run_preflight(
        root=ROOT,
        env_dirs=(),
        env_names=("sheaf_schema_sync",),
        stage="offline",
        matrices=("representative",),
        environ={
            "AGENTROUTER_API_KEY": FAKE_KEY,
            "AGENTROUTER_API_BASE": "https://router.example.invalid/v1",
        },
    )
    plan = _stage(report, "plan")
    assert "$AGENTROUTER_API_BASE" in plan["commands"]["one_case_rehearsal"]
    assert "$AGENTROUTER_API_BASE" in plan["commands"]["dry_run"]
    assert "router.example.invalid/v1" not in json.dumps(report)
    assert _stage(report, "credential")["api_base_source"] == "env:AGENTROUTER_API_BASE"


def test_the_wire_stage_is_skipped_when_the_catalog_matched_nothing() -> None:
    report = probe.run_preflight(
        root=ROOT,
        env_dirs=(),
        env_names=("rd_state_carry",),
        stage="all",
        matrices=("representative",),
        api_base=None,
        environ={},
    )
    stages = {stage["stage"] for stage in report["stages"]}
    assert "wire" not in stages
    assert "catalog" in stages
    assert _stage(report, "catalog")["status"] == "skipped"


def test_the_plan_stage_bounds_the_first_live_run() -> None:
    report = probe.run_preflight(
        root=ROOT,
        env_dirs=(),
        env_names=("sheaf_schema_sync",),
        stage="offline",
        matrices=("representative", "pairwise"),
        max_steps=6,
        environ={},
    )
    plan = _stage(report, "plan")
    assert plan["matrices"]["representative"]["case_count"] == 1
    assert plan["matrices"]["pairwise"]["case_count"] >= 1
    assert plan["matrices"]["representative"]["estimated_api_calls_at_max_steps"] == 6
    rehearsal = plan["commands"]["one_case_rehearsal"]
    for bound in ("--max-cases 1", "--max-api-calls 6", "--max-wall-seconds", "--sandbox docker"):
        assert bound in rehearsal
    assert "--provider custom" in rehearsal
    assert "--api-key-env AGENTROUTER_API_KEY" in rehearsal
    assert "--dry-run" in plan["commands"]["dry_run"]


def test_the_emitted_manifest_only_contains_the_selected_environments(tmp_path: Path) -> None:
    wanted = probe.selected_environments(ROOT)
    out = tmp_path / "manifest.json"
    summary = probe.emit_manifest(ROOT, wanted["environments"], "representative", out)
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert summary["case_count"] == len(manifest["cases"]) == 6
    assert {case["environment"] for case in manifest["cases"]} == SIX
    assert manifest["selection"]["selected_by"] == "tools/provider_env_preflight.py"


LAUNCHER = ROOT / "docs" / "workflows" / "agentrouter-astra-env-preflight.yml.example"


def test_the_copyable_launcher_stays_inside_the_probes_own_cli() -> None:
    """An example that calls a flag the tool does not have is worse than no example."""

    text = LAUNCHER.read_text(encoding="utf-8")
    invocation = text.split("python tools/provider_env_preflight.py", 1)[1].split("--out", 1)[0]
    valid = {flag for action in probe.build_parser()._actions for flag in action.option_strings}
    used = set(re.findall(r"--[a-z][a-z0-9-]*", invocation))
    assert used, "the launcher has to actually call the probe"
    assert used <= valid, sorted(used - valid)


def test_the_launcher_only_carries_urls_somebody_published() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    documented_base, citation = probe.DOCUMENTED_BASES["agentrouter"]
    urls = {url.rstrip(".,;") for url in re.findall(r"https://[^\s\"')]+", text)}
    assert urls <= {
        "https://download.pytorch.org/whl/cpu",
        documented_base,
        citation,
        "https://ps.air-outer.com/console/personal",
    }, sorted(urls)
    # The input default and the probe's documented default are the same string, so
    # the launcher cannot drift away from the citation it claims to follow.
    assert f'default: "{documented_base}"' in text
    assert "AGENTROUTER_API_BASE: ${{ inputs.api_base }}" in text
    assert "secrets.AGENTROUTER_API_KEY" in text


def test_a_503_is_read_as_a_roster_problem_not_as_a_dead_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_503(req: Any, timeout: float) -> Any:
        raise error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(probe, "open_no_redirect", raise_503)
    stage = probe.stage_catalog(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://agentrouter.org/v1",
        api_key=FAKE_KEY,
        model_filter="astra",
        timeout=5.0,
    )
    assert stage["status"] == "http_error"
    assert stage["status_code"] == 503
    assert any("no available channel" in note for note in stage["notes"])


def test_a_rejected_size_key_names_the_file_that_owns_it() -> None:
    class _Refusing:
        def complete(self, **kwargs: Any) -> Completion:
            raise ProviderError(
                "unsupported parameter",
                status_code=400,
                body="unsupported parameter: 'max_tokens' is not allowed with this model",
            )

    stage = probe.stage_wire(
        provider="agentrouter",
        wire_provider="custom",
        api_base="https://agentrouter.org/v1",
        api_key=FAKE_KEY,
        model="gpt-6-astra",
        max_tokens=96,
        timeout=5.0,
        client_factory=lambda: _Refusing(),
    )
    assert stage["status"] == "provider_error"
    assert stage["status_code"] == 400
    assert stage["error_type"] == "http_400"
    assert any("_MAX_TOKENS_KEY" in note and "verdict-relevant" in note for note in stage["notes"])
    assert FAKE_KEY not in json.dumps(stage)


def test_the_summary_names_the_verdict_and_the_next_step() -> None:
    report = probe.run_preflight(
        root=ROOT,
        env_dirs=(),
        env_names=("sheaf_schema_sync",),
        stage="offline",
        matrices=("representative",),
        environ={},
    )
    text = probe.summarize(report)
    assert "VERDICT: unknown_needs_ci" in text
    assert "NEXT:" in text
    assert "- env_build: ready" in text
    assert FAKE_KEY not in text
