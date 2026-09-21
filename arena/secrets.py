"""Host-only credential profiles and redaction helpers.

Credentials may come from an explicit CLI value, an explicitly named
environment variable, a provider-specific environment variable, or a local
``secret_key.json`` profile.  This module never writes credentials and never
returns them in metadata intended for artifacts.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE_NAME = "secret_key.json"
SECRET_FILE_CANDIDATES = (
    Path.cwd() / SECRET_FILE_NAME,
    Path.home() / ".config" / "rl_eval_generator" / SECRET_FILE_NAME,
)

PROVIDER_ENV: dict[str, tuple[str, ...]] = {
    "groq": ("GROQ_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "cloudflare": ("CF_API_TOKEN",),
    "atria": ("ATRIA_API_KEY",),
    "custom": ("API_KEY",),
    "huggingface": ("HF_TOKEN",),
}

PROVIDER_DEFAULT_BASE: dict[str, str | None] = {
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
    "cloudflare": None,
    "atria": "https://api.atria-asi.ai/v1",
    "custom": None,
    "huggingface": "https://router.huggingface.co/v1",
}

# These patterns are only a fallback for values that were not loaded through a
# profile.  Known loaded values are always replaced literally as well.
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:gsk_|sk-or-v1-|nvapi-|AIza)[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)\b(?:bearer\s+)([^\s,\"'}]+)"),
    re.compile(r"(?i)(api[_-]?key|authorization|token)(\s*[:=]\s*)(['\"]?)([^\s,'\"}]+)\3"),
)
_LOADED_SECRET_VALUES: set[str] = set()


@dataclass(frozen=True)
class ProviderCreds:
    """Resolved provider settings kept in host memory only."""

    name: str
    api_key: str
    api_base: str
    enabled: bool = True
    default_model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    source: str = ""


def _remember_secret(value: str | None) -> None:
    if value and len(value) >= 4:
        _LOADED_SECRET_VALUES.add(value)


def redact_text(text: str, secrets: Mapping[str, str] | list[str] | tuple[str, ...] | None = None) -> str:
    """Redact loaded credentials and common bearer/key forms from text."""

    output = str(text)
    values = set(_LOADED_SECRET_VALUES)
    if isinstance(secrets, Mapping):
        values.update(str(value) for value in secrets.values() if value)
    elif secrets:
        values.update(str(value) for value in secrets if value)
    for value in sorted(values, key=len, reverse=True):
        output = output.replace(value, "[REDACTED]")

    def bearer(match: re.Match[str]) -> str:
        return match.group(0)[: match.start(1) - match.start(0)] + "[REDACTED]"

    output = _SECRET_PATTERNS[0].sub("[REDACTED]", output)
    output = _SECRET_PATTERNS[1].sub(bearer, output)
    output = _SECRET_PATTERNS[2].sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", output)
    return output


def _git_check(path: Path, *args: str) -> bool:
    try:
        result = subprocess.run(
            ["git", *args, "--", str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def ensure_secret_file_safe(path: Path) -> None:
    """Reject tracked or broadly readable secret files in the repository."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    if _git_check(resolved, "ls-files", "--error-unmatch"):
        raise ValueError(f"refusing to load tracked secret file: {resolved}")
    if not _git_check(resolved, "check-ignore", "-q"):
        raise ValueError(
            f"secret file is not gitignored: {resolved}; add it to .gitignore before loading"
        )
    try:
        mode = stat.S_IMODE(resolved.stat().st_mode)
    except OSError as exc:
        raise ValueError(f"cannot inspect secret file permissions: {resolved}") from exc
    if mode & 0o077:
        raise ValueError(f"secret file must be private (chmod 600): {resolved}")


def _secret_paths(explicit: Path | None) -> list[Path]:
    if explicit is not None:
        return [explicit.expanduser()]
    return [path for path in SECRET_FILE_CANDIDATES if path.is_file()]


def load_secret_config(path: Path | None = None) -> tuple[dict[str, Any], Path | None]:
    """Load a profile, returning ``({}, None)`` when no optional profile exists."""

    paths = _secret_paths(path)
    if path is not None and not paths[0].is_file():
        raise ValueError(f"secret file not found: {paths[0]}")
    for candidate in paths:
        ensure_secret_file_safe(candidate)
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in secret file: {candidate}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"secret file must contain a JSON object: {candidate}")
        providers = loaded.get("providers", {})
        if not isinstance(providers, dict):
            raise ValueError(f"secret file providers must be an object: {candidate}")
        for profile in providers.values():
            if isinstance(profile, dict) and profile.get("api_key"):
                _remember_secret(str(profile["api_key"]))
        return loaded, candidate
    return {}, None


def provider_profile(name: str, secret_path: Path | None = None) -> tuple[dict[str, Any], dict[str, Any], Path | None]:
    normalized = name.strip().lower()
    if normalized not in PROVIDER_DEFAULT_BASE:
        known = ", ".join(sorted(PROVIDER_DEFAULT_BASE))
        raise ValueError(f"unknown provider {name!r}; choose from {known}")
    config, loaded_path = load_secret_config(secret_path)
    providers = config.get("providers", {})
    profile = providers.get(normalized, {}) if isinstance(providers, dict) else {}
    if profile is None:
        profile = {}
    if not isinstance(profile, dict):
        raise ValueError(f"providers.{normalized} must be an object")
    return config, profile, loaded_path


def resolve_provider(
    name: str,
    *,
    api_key: str | None = None,
    api_key_env: str | None = None,
    api_base: str | None = None,
    secret_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    require_key: bool = True,
) -> ProviderCreds:
    """Resolve one profile without printing its key.

    Precedence is CLI key, explicit CLI environment variable, provider
    environment variable, then the local profile file.  API base precedence is
    explicit CLI base, profile base, then the built-in provider default.
    """

    normalized = name.strip().lower()
    config, profile, loaded_path = provider_profile(normalized, secret_path)
    env = environ if environ is not None else os.environ
    env_names = list(PROVIDER_ENV[normalized])
    if api_key_env:
        env_names = [api_key_env] + [name for name in env_names if name != api_key_env]
    selected_env = env_names[0] if env_names else None
    key = api_key
    source = "cli"
    if not key:
        for env_name in env_names:
            if env.get(env_name):
                key = env[env_name]
                selected_env = env_name
                source = f"env:{env_name}"
                break
    if not key and profile.get("api_key"):
        key = str(profile["api_key"])
        source = f"file:{loaded_path}" if loaded_path else "file"
    if require_key and not key:
        env_hint = selected_env or PROVIDER_ENV[normalized][0]
        raise ValueError(
            f"No API key for provider {normalized!r}; set {env_hint} or add "
            f"providers.{normalized}.api_key to secret_key.json"
        )
    base = api_base or profile.get("api_base") or PROVIDER_DEFAULT_BASE[normalized]
    if not base:
        raise ValueError(
            f"No API base for provider {normalized!r}; pass --api-base or set "
            f"providers.{normalized}.api_base in secret_key.json"
        )
    if key:
        _remember_secret(str(key))
    default_models = config.get("default_models", {})
    default_model = default_models.get(normalized) if isinstance(default_models, dict) else None
    extra = {
        key_name: value
        for key_name, value in profile.items()
        if key_name not in {"api_key", "api_base", "enabled", "notes"}
    }
    return ProviderCreds(
        name=normalized,
        api_key=str(key or ""),
        api_base=str(base).rstrip("/"),
        enabled=bool(profile.get("enabled", True)),
        default_model=str(default_model) if default_model else None,
        extra=extra,
        source=source,
    )


def provider_environment_name(name: str, api_key_env: str | None = None) -> str:
    normalized = name.strip().lower()
    if api_key_env:
        return api_key_env
    return PROVIDER_ENV[normalized][0]


__all__ = [
    "PROVIDER_DEFAULT_BASE",
    "PROVIDER_ENV",
    "ProviderCreds",
    "SECRET_FILE_CANDIDATES",
    "ensure_secret_file_safe",
    "load_secret_config",
    "provider_environment_name",
    "provider_profile",
    "redact_text",
    "resolve_provider",
]
