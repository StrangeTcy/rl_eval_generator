from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from arena.episode import _controller_environment
from arena.providers import (
    PROVIDERS,
    ProviderClient,
    ProviderError,
    chat_completions_url,
    provider_auth_headers,
)
from arena.secrets import (
    PROVIDER_DEFAULT_BASE,
    PROVIDER_ENV,
    redact_text,
    resolve_provider,
)
from tools import recursive_gluing_study as study
from tools.provider_preflight import _headers as preflight_headers, _models_url
from tools.run_suite import _build_command, _load_checkpoint

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "yepapi": {
        "key_env": "YEPAPI_KEY",
        "base": "https://api.yepapi.com/v1/ai",
        "model": "openai/gpt-6-astra",
        "auth_header": "x-api-key",
    },
    "synapse_garden": {
        "key_env": "SYNAPSE_API_KEY",
        "base": "https://synapse.garden/api/v1",
        "model": "openai/gpt-6.1-sol",
        "auth_header": "Authorization",
    },
}


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _RecordingOpener:
    def __init__(self) -> None:
        self.url: str | None = None
        self.headers: dict[str, str] = {}
        self.body: dict | None = None

    def __call__(self, req, timeout=None):
        self.url = req.full_url
        self.headers = {key.lower(): value for key, value in req.header_items()}
        self.body = json.loads(req.data.decode("utf-8"))
        return _Response(
            {
                "model": self.body["model"],
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        )


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_credentials_are_provider_specific_and_ignore_generic_api_key(provider, profile):
    key = f"offline-{provider}-credential"
    resolved = resolve_provider(
        provider,
        environ={"API_KEY": "must-not-be-used", profile["key_env"]: key},
    )
    assert PROVIDER_ENV[provider] == (profile["key_env"],)
    assert resolved.name == provider
    assert resolved.api_key == key
    assert resolved.api_base == profile["base"]
    assert PROVIDER_DEFAULT_BASE[provider] == profile["base"]
    assert PROVIDERS[provider] == {"api_base": profile["base"], "key_env": profile["key_env"]}
    assert chat_completions_url(resolved.api_base) == profile["base"] + "/chat/completions"
    assert _models_url(resolved.api_base) == profile["base"] + "/models"


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_chat_client_uses_expected_endpoint_auth_header_and_model(provider, profile):
    key = f"offline-{provider}-credential"
    opener = _RecordingOpener()
    client = ProviderClient(provider, key, opener=opener, max_retries=0)
    completion = client.complete(
        model=profile["model"],
        messages=[{"role": "user", "content": "offline test"}],
        max_tokens=64,
        temperature=0.0,
    )

    assert opener.url == profile["base"] + "/chat/completions"
    assert opener.body is not None
    assert opener.body["model"] == profile["model"]
    assert opener.body["messages"] == [{"role": "user", "content": "offline test"}]
    assert opener.body["stream"] is False
    assert profile["auth_header"].lower() in opener.headers
    if provider == "yepapi":
        assert opener.headers["x-api-key"] == key
        assert "authorization" not in opener.headers
    else:
        assert opener.headers["authorization"] == f"Bearer {key}"
        assert "x-api-key" not in opener.headers
    assert completion.provider == provider
    assert completion.requested_model == profile["model"]


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_preflight_uses_the_same_provider_auth_policy(provider, profile):
    key = f"offline-{provider}-credential"
    headers = {name.lower(): value for name, value in preflight_headers(provider, key).items()}
    assert headers[profile["auth_header"].lower()] == (
        key if provider == "yepapi" else f"Bearer {key}"
    )
    assert "authorization" not in headers if provider == "yepapi" else "x-api-key" not in headers


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_study_plan_gate_and_report_keep_provider_model_base_and_protocol(provider, profile):
    manifest, plan = study.build_study_manifest(
        scope="diagnostic",
        provider=provider,
        model=profile["model"],
        wire_api="chat_completions",
        created_at="2026-10-21T00:00:00Z",
    )
    assert manifest["study"]["provider"] == plan["provider"] == provider
    assert manifest["study"]["model"] == plan["model"] == profile["model"]
    assert manifest["study"]["wire_api"] == plan["wire_api"] == "chat_completions"
    assert plan["api_base"] is None

    captured: dict = {}

    def runner(_manifest, **kwargs):
        captured.update(kwargs)
        return {
            "run": {
                "provider": kwargs["provider"],
                "model": kwargs["model"],
                "api_base": kwargs["api_base"],
                "wire_api": kwargs["wire_api"],
                "api_key_env": kwargs["api_key_env"],
            },
            "results": [],
        }

    result = study.run_study(
        manifest,
        execution_mode="gates_only",
        provider=provider,
        model=profile["model"],
        output_dir=ROOT / "runs" / "test-provider-forwarding",
        api_base=profile["base"],
        wire_api="chat_completions",
        max_api_calls=2000,
        max_tokens_total=8_000_000,
        max_wall_seconds=14_400,
        max_steps=24,
        max_tokens=4096,
        runner=runner,
    )
    assert captured["provider"] == provider
    assert captured["model"] == profile["model"]
    assert captured["api_base"] == profile["base"]
    assert captured["wire_api"] == "chat_completions"
    assert captured["api_key_env"] == profile["key_env"]
    assert result["checkpoint"]["run"]["api_key_env"] == profile["key_env"]

    report = study.build_report(manifest, result["checkpoint"])
    assert report["run"]["provider"] == provider
    assert report["run"]["model"] == profile["model"]
    assert report["run"]["api_base"] == profile["base"]
    assert report["run"]["wire_api"] == "chat_completions"


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_study_profile_rejects_non_chat_protocol(provider, profile):
    with pytest.raises(study.StudyError, match="chat_completions"):
        study.build_study_manifest(
            scope="diagnostic",
            provider=provider,
            model=profile["model"],
            wire_api="responses",
            created_at="2026-10-21T00:00:00Z",
        )


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_live_command_and_checkpoint_preserve_provider_model_base_and_protocol(
    provider, profile, tmp_path
):
    key = f"offline-{provider}-credential"
    command = _build_command(
        case={"environment": "synthetic_env", "difficulty": "easy", "seed": 4},
        provider=provider,
        model=profile["model"],
        api_key_env=profile["key_env"],
        secrets=None,
        api_base=profile["base"],
        sandbox="docker",
        output_dir=tmp_path,
        max_steps=1,
        max_tokens=64,
        invalid_retries=0,
        keep_images=False,
        keep_workspace=False,
        wire_api="chat_completions",
    )
    assert command[command.index("--provider") + 1] == provider
    assert command[command.index("--model") + 1] == profile["model"]
    assert command[command.index("--api-key-env") + 1] == profile["key_env"]
    assert command[command.index("--api-base") + 1] == profile["base"]
    assert command[command.index("--wire-api") + 1] == "chat_completions"
    assert key not in command  # only the environment-variable name crosses this boundary

    metadata = {
        "manifest_commit": "offline-test",
        "provider": provider,
        "model": profile["model"],
        "api_base": profile["base"],
        "sandbox": "docker",
        "api_key_env": profile["key_env"],
        "secrets": None,
        "max_steps": 1,
        "max_tokens": 64,
        "temperature": 0.0,
        "top_p": None,
        "invalid_retries": 0,
        "max_retries": 0,
        "max_http_attempts": 10,
        "provider_min_interval_seconds": 0.0,
        "max_api_calls": 10,
        "max_tokens_total": 640,
        "floor_effect_after": None,
        "wire_api": "chat_completions",
        "reasoning_effort": None,
        "request_extra": {},
    }
    checkpoint = _load_checkpoint(
        tmp_path / "suite_checkpoint.json",
        manifest={"case_count": 1, "cases": [{}]},
        metadata=metadata,
    )
    for field in ("provider", "model", "api_base", "api_key_env", "wire_api"):
        assert checkpoint["run"][field] == metadata[field]
    assert key not in json.dumps(checkpoint)


@pytest.mark.parametrize("provider,profile", PROFILES.items())
def test_chat_only_provider_rejects_responses_protocol(provider, profile):
    client = ProviderClient(provider, "offline-only-test-key")
    with pytest.raises(ValueError, match="Chat Completions only"):
        client.complete_responses(input_text="offline", model=profile["model"])


def test_credentials_are_redacted_and_removed_from_agent_judge_environment(monkeypatch):
    keys = {
        "YEPAPI_KEY": "offline-yepapi-sensitive-value",
        "SYNAPSE_API_KEY": "offline-synapse-sensitive-value",
    }
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
        resolve_provider(
            "yepapi" if name == "YEPAPI_KEY" else "synapse_garden",
            environ={name: value},
        )
        assert value not in redact_text(f"header={value}; Authorization: Bearer {value}")
        assert "[REDACTED]" in redact_text(f"header={value}")

    controller_env = _controller_environment()
    assert all(name not in controller_env for name in keys)


def test_provider_client_redacts_credentials_from_error_records():
    from urllib.error import HTTPError
    from io import BytesIO

    key = "offline-yepapi-sensitive-value"

    class _ErrorOpener:
        def __call__(self, req, timeout=None):
            raise HTTPError(
                req.full_url,
                401,
                "bad key " + key,
                {"x-api-key": key, "X-Request-ID": "request-1"},
                BytesIO(("rejected " + key).encode()),
            )

    client = ProviderClient("yepapi", key, opener=_ErrorOpener(), max_retries=0)
    with pytest.raises(ProviderError) as exc:
        client.complete(
            model=PROFILES["yepapi"]["model"],
            messages=[{"role": "user", "content": "test"}],
            max_tokens=10,
            temperature=0.0,
        )
    serialized = json.dumps(
        {
            "exception": str(exc.value),
            "body": exc.value.body,
            "headers": exc.value.response_headers,
            "attempt_logs": client.last_attempt_logs,
        }
    )
    assert key not in serialized
    assert "x-api-key" not in {name.lower() for name in exc.value.response_headers}


def test_workflow_source_choices_and_secrets_are_live_step_only():
    example_path = ROOT / "docs/workflows/recursive-gluing-eval.yml.example"
    workflow = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    on_block = workflow.get("on", workflow.get(True))
    providers = on_block["workflow_dispatch"]["inputs"]["provider"]["options"]
    assert {"yepapi", "synapse_garden", "custom"}.issubset(set(providers))

    jobs = workflow["jobs"]
    live_step = next(
        step for step in jobs["evaluate"]["steps"]
        if step.get("name", "").startswith("Live evaluation")
    )
    live_env = live_step["env"]
    assert live_env["YEPAPI_KEY"] == "${{ secrets.YEPAPI_KEY }}"
    assert live_env["SYNAPSE_API_KEY"] == "${{ secrets.SYNAPSE_API_KEY }}"
    assert "YEPAPI_KEY" not in jobs["evaluate"].get("env", {})
    assert "SYNAPSE_API_KEY" not in jobs["evaluate"].get("env", {})
    for step in jobs["evaluate"]["steps"]:
        if step is live_step:
            continue
        assert "YEPAPI_KEY" not in step.get("env", {})
        assert "SYNAPSE_API_KEY" not in step.get("env", {})
