from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import HTTPError

import tools.provider_preflight as provider_preflight
from arena.secrets import ensure_secret_file_safe, redact_text, resolve_provider
from tools.configure_provider import main as configure_provider_main
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


def test_configure_provider_from_env_preserves_profile_and_redacts_output(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "secret_key.json"
    profile.write_text(
        json.dumps(
            {
                "providers": {
                    "groq": {"api_key": "unrelated", "notes": "keep this"}
                },
                "default_provider": "groq",
                "metadata": {"pilot": "preserve"},
            }
        ),
        encoding="utf-8",
    )
    profile.chmod(0o600)
    canary = "nvapi-fake-credential-for-test"
    monkeypatch.setenv("NVIDIA_API_KEY", canary)
    assert configure_provider_main(
        [
            "--provider",
            "nvidia",
            "--from-env",
            "NVIDIA_API_KEY",
            "--out",
            str(profile),
        ]
    ) == 0
    captured = capsys.readouterr()
    assert canary not in captured.out
    assert canary not in captured.err
    loaded = json.loads(profile.read_text(encoding="utf-8"))
    assert loaded["providers"]["groq"] == {"api_key": "unrelated", "notes": "keep this"}
    assert loaded["metadata"] == {"pilot": "preserve"}
    assert loaded["providers"]["nvidia"]["api_key"] == canary
    assert (profile.stat().st_mode & 0o777) == 0o600


def test_configure_provider_refuses_replacement_without_explicit_flag(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "secret_key.json"
    _write_profile(profile, key="existing-fake-key")
    monkeypatch.setenv("GROQ_API_KEY", "replacement-fake-key")
    assert configure_provider_main(
        [
            "--provider",
            "groq",
            "--from-env",
            "GROQ_API_KEY",
            "--out",
            str(profile),
        ]
    ) == 2
    assert "replacement-fake-key" not in capsys.readouterr().err
    assert "existing-fake-key" in profile.read_text(encoding="utf-8")


def test_configure_provider_prompt_refuses_non_tty(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tools.configure_provider.sys.stdin.isatty", lambda: False)
    assert configure_provider_main(
        ["--provider", "nvidia", "--prompt", "--out", str(tmp_path / "secret_key.json")]
    ) == 2
    assert "credential" not in capsys.readouterr().out.lower()


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


def test_external_profile_permissions_are_enforced(tmp_path):
    profile = tmp_path / "secret_key.json"
    _write_profile(profile, key="external-canary")
    profile.chmod(0o644)
    try:
        ensure_secret_file_safe(profile)
    except ValueError as exc:
        assert "private" in str(exc)
    else:
        raise AssertionError("world-readable external profile must be rejected")

    profile.chmod(0o600)
    ensure_secret_file_safe(profile)
    resolved = resolve_provider("groq", secret_path=profile, environ={})
    assert resolved.api_key == "external-canary"


def test_repository_profile_must_be_untracked_and_ignored():
    unignored = Path(__file__).resolve().parents[1] / "tests" / ".secret-regression.json"
    unignored.write_text("{}", encoding="utf-8")
    unignored.chmod(0o600)
    try:
        try:
            ensure_secret_file_safe(unignored)
        except ValueError as exc:
            assert "gitignored" in str(exc)
        else:
            raise AssertionError("unignored repository profile must be rejected")
    finally:
        unignored.unlink(missing_ok=True)

    tracked = Path(__file__).resolve().parents[1] / "README.md"
    original_mode = tracked.stat().st_mode & 0o777
    try:
        tracked.chmod(0o600)
        try:
            ensure_secret_file_safe(tracked)
        except ValueError as exc:
            assert "tracked" in str(exc)
        else:
            raise AssertionError("tracked profile must be rejected")
    finally:
        tracked.chmod(original_mode)


def test_preflight_never_persists_or_prints_error_body_canary(tmp_path, monkeypatch, capsys):
    canary = "error-body-credential-canary"
    profile = tmp_path / "secret_key.json"
    _write_profile(profile, key=canary)

    def fake_open(req, timeout):
        raise HTTPError(
            req.full_url,
            401,
            "unauthorized",
            {"X-Request-ID": "request-canary"},
            io.BytesIO(canary.encode()),
        )

    monkeypatch.setattr(provider_preflight, "open_no_redirect", fake_open)
    output = tmp_path / "preflight.json"
    assert provider_preflight.main(
        ["--secrets", str(profile), "--provider", "groq", "--out", str(output)]
    ) == 1
    report = output.read_text(encoding="utf-8")
    stdout = capsys.readouterr().out
    assert canary not in report
    assert canary not in stdout
    assert '"error":' not in report
    report_value = json.loads(report)
    assert set(report_value["providers"][0]) <= {
        "provider",
        "status",
        "status_code",
        "error_type",
        "request_id",
        "latency_ms",
        "model_ids",
    }


def test_preflight_sanitizes_purported_model_id_canary(tmp_path, monkeypatch, capsys):
    canary = "model-id-credential-canary"
    profile = tmp_path / "secret_key.json"
    _write_profile(profile, key=canary)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"data": [{"id": canary}]}).encode()

    monkeypatch.setattr(provider_preflight, "open_no_redirect", lambda req, timeout: Response())
    output = tmp_path / "preflight.json"
    assert provider_preflight.main(
        ["--secrets", str(profile), "--provider", "groq", "--out", str(output)]
    ) == 0
    report = output.read_text(encoding="utf-8")
    stdout = capsys.readouterr().out
    assert canary not in report
    assert canary not in stdout
