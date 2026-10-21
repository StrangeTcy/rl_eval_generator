from __future__ import annotations

from pathlib import Path

import pytest

from arena.providers import PROVIDERS
from arena.secrets import PROVIDER_DEFAULT_BASE, PROVIDER_ENV, resolve_provider
from tools import recursive_gluing_study as study

ROOT = Path(__file__).resolve().parents[1]
AGENTROUTER_BASE = "https://agentrouter.org/v1"


def test_agentrouter_is_a_first_class_openai_compatible_provider() -> None:
    assert PROVIDER_ENV["agentrouter"] == (
        "AGENTROUTER_API_KEY", "AGENT_ROUTER_API_KEY", "AGENTROUTER_API_TOKEN"
    )
    assert PROVIDER_DEFAULT_BASE["agentrouter"] == AGENTROUTER_BASE
    assert PROVIDERS["agentrouter"] == {
        "api_base": AGENTROUTER_BASE,
        "key_env": "AGENTROUTER_API_KEY",
    }


@pytest.mark.parametrize("key_env", PROVIDER_ENV["agentrouter"])
def test_agentrouter_resolves_each_supported_credential_alias(key_env: str) -> None:
    resolved = resolve_provider(
        "agentrouter",
        environ={key_env: "test-key"},
    )
    assert resolved.name == "agentrouter"
    assert resolved.api_key == "test-key"
    assert resolved.api_base == AGENTROUTER_BASE


def test_recursive_study_defaults_to_agentrouter_and_records_explicit_provider() -> None:
    manifest, plan = study.build_study_manifest(
        scope="diagnostic",
        model="gpt-6-astra",
        created_at="2026-10-21T00:00:00Z",
    )
    assert manifest["study"]["provider"] == "agentrouter"
    assert plan["provider"] == "agentrouter"
    # A null override means the built-in AgentRouter endpoint is used at runtime;
    # the provider key and wire protocol are still fixed in the manifest.
    assert plan["api_base"] is None
    assert plan["wire_api"] == "chat_completions"


def test_agentrouter_rejects_the_responses_wire_protocol() -> None:
    with pytest.raises(study.StudyError, match="AgentRouter.*chat_completions"):
        study.build_study_manifest(
            scope="diagnostic",
            provider="agentrouter",
            model="gpt-6-astra",
            wire_api="responses",
            created_at="2026-10-21T00:00:00Z",
        )


def test_workflow_exposes_agentrouter_choice_and_secret_and_mirrors_example() -> None:
    example = ROOT / "docs/workflows/recursive-gluing-eval.yml.example"
    content = example.read_text(encoding="utf-8")
    assert "          - agentrouter\n" in content
    assert "        default: agentrouter\n" in content
    assert "        required: true\n" in content
    assert "AGENTROUTER_API_KEY: ${{ secrets.AGENTROUTER_API_KEY }}" in content
    assert "AGENT_ROUTER_API_KEY: ${{ secrets.AGENT_ROUTER_API_KEY }}" in content
    assert "AGENTROUTER_API_TOKEN: ${{ secrets.AGENTROUTER_API_TOKEN }}" in content
