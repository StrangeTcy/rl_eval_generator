#!/usr/bin/env python3
"""Create or update a private provider profile without exposing its key."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.providers import PROVIDERS, require_https  # noqa: E402
from arena.secrets import ensure_secret_file_safe  # noqa: E402

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _git_ignored(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(path)],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _inside_repository(path: Path) -> bool:
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return False
    return True


def _validate_destination(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        ensure_secret_file_safe(resolved)
    elif _inside_repository(resolved) and not _git_ignored(resolved):
        raise ValueError(
            f"secret file is not gitignored: {resolved}; add it to .gitignore before creating it"
        )
    return resolved


def _read_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in existing secret file: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("existing secret file must contain a JSON object")
    providers = value.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("existing secret file providers must be an object")
    return value


def _hidden_key() -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("hidden prompt requires a TTY; refusing echoed input")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", getpass.GetPassWarning)
        try:
            value = getpass.getpass("Provider API key: ")
            confirmation = getpass.getpass("Confirm provider API key: ")
        except (EOFError, KeyboardInterrupt) as exc:
            raise RuntimeError("hidden credential entry was cancelled") from exc
    if caught:
        raise RuntimeError("hidden prompt was unavailable; refusing echoed input")
    if not value:
        raise ValueError("provider API key must not be empty")
    if value != confirmation:
        raise ValueError("provider API key confirmation did not match")
    return value


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        encoded = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        ensure_secret_file_safe(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def configure_provider(
    *,
    provider: str,
    output: Path,
    api_key: str,
    api_base: str | None = None,
    model: str | None = None,
    replace: bool = False,
) -> Path:
    """Write one provider key while preserving all unrelated profile data."""

    normalized = provider.strip().lower()
    if normalized not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    if not api_key:
        raise ValueError("provider API key must not be empty")
    destination = _validate_destination(output)
    document = _read_existing(destination)
    provider_profiles = document.setdefault("providers", {})
    if not isinstance(provider_profiles, dict):
        raise ValueError("secret file providers must be an object")
    current = provider_profiles.get(normalized, {})
    if current is None:
        current = {}
    if not isinstance(current, dict):
        raise ValueError(f"providers.{normalized} must be an object")
    if current.get("api_key") and not replace:
        raise ValueError(
            f"providers.{normalized}.api_key already exists; pass --replace to replace it explicitly"
        )
    base = api_base or current.get("api_base") or PROVIDERS[normalized]["api_base"]
    if not base:
        raise ValueError(f"an HTTPS API base is required for provider {normalized}")
    require_https(str(base))
    updated = dict(current)
    updated.update({"api_key": api_key, "api_base": str(base), "enabled": True})
    provider_profiles[normalized] = updated
    document.setdefault("default_provider", normalized)
    if model:
        default_models = document.setdefault("default_models", {})
        if not isinstance(default_models, dict):
            raise ValueError("secret file default_models must be an object")
        default_models[normalized] = model
    _atomic_write(destination, document)
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--out", type=Path, default=Path("secret_key.json"))
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--replace", action="store_true")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt", action="store_true", help="read the key with hidden TTY input")
    source.add_argument("--from-env", metavar="ENV_NAME", help="read the key from this environment variable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.prompt:
            key = _hidden_key()
        else:
            if not _ENV_NAME.fullmatch(args.from_env):
                raise ValueError("--from-env must be a valid environment variable name")
            key = os.environ.get(args.from_env, "")
            if not key:
                raise ValueError(f"environment variable {args.from_env} is not set")
        destination = configure_provider(
            provider=args.provider,
            output=args.out,
            api_key=key,
            api_base=args.api_base,
            model=args.model,
            replace=args.replace,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"configure_provider failed: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote private provider profile to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
