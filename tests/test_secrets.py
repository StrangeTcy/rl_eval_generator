from __future__ import annotations

import json
from pathlib import Path

from arena.secrets import redact_text, resolve_provider
from tools.provider_preflight import run_preflight


def _write_profile(path: Path, key: str = "gsk_file_secret") -> None:
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "groq": {
                        "api_key": key,
                        "api_base": "https://groq.example/v1",
                        "enabled": True,
                    }
                },
                "default_models": {"groq": "test/model"},
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_provider_resolution_precedence_and_redaction(tmp_path):
    profile = tmp_path / "secret_key.json"
    _write_profile(profile)
    environment = {"GROQ_API_KEY": "gsk_environment_secret"}
    resolved = resolve_provider("groq", secret_path=profile, environ=environment)
    assert resolved.api_key == "gsk_environment_secret"
    assert resolved.api_base == "https://groq.example/v1"
    assert resolved.default_model == "test/model"
    fallback = resolve_provider(
        "groq",
        api_key_env="MISSING_PROVIDER_KEY",
        secret_path=profile,
        environ=environment,
    )
    assert fallback.api_key == "gsk_environment_secret"

    explicit = resolve_provider(
        "groq",
        api_key="gsk_cli_secret",
        secret_path=profile,
        environ=environment,
    )
    assert explicit.api_key == "gsk_cli_secret"
    assert "gsk_cli_secret" not in redact_text("Authorization: Bearer gsk_cli_secret")
    assert "REDACTED" in redact_text("Authorization: Bearer gsk_cli_secret")


def test_provider_preflight_missing_key_does_not_make_network_request(tmp_path):
    profile = tmp_path / "secret_key.json"
    profile.write_text(json.dumps({"providers": {"groq": {"enabled": True}}}), encoding="utf-8")
    profile.chmod(0o600)
    result = run_preflight(secret_path=profile, providers=["groq"], timeout=0.01)
    assert result["failure_count"] == 1
    assert result["providers"][0]["status"] == "credential_error"
    assert "gsk_" not in json.dumps(result)
