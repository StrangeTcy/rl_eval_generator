#!/usr/bin/env python3
"""Probe enabled OpenAI-compatible provider profiles without logging keys."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.secrets import load_secret_config, redact_text, resolve_provider  # noqa: E402


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _models_url(base: str) -> str:
    return base.rstrip("/") + "/models"


def _headers(provider: str, key: str) -> dict[str, str]:
    value = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        value.update(
            {
                "HTTP-Referer": "https://github.com/StrangeTcy/rl_eval_generator",
                "X-OpenRouter-Title": "rl_eval_generator",
            }
        )
    return value


def _extract_models(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("id") is not None:
            ids.append(str(item["id"]))
    return ids


def probe_provider(name: str, *, secret_path: Path | None, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        creds = resolve_provider(name, secret_path=secret_path)
    except (OSError, ValueError) as exc:
        return {
            "provider": name,
            "status": "credential_error",
            "error": redact_text(str(exc)),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    url = _models_url(creds.api_base)
    try:
        req = request.Request(url, headers=_headers(creds.name, creds.api_key), method="GET")
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
        payload = json.loads(body)
        model_ids = _extract_models(payload)
        return {
            "provider": creds.name,
            "status": "reachable",
            "api_base": creds.api_base,
            "models_url": url,
            "status_code": status_code,
            "model_count": len(model_ids),
            "model_ids": model_ids,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "provider": creds.name,
            "status": "http_error",
            "api_base": creds.api_base,
            "models_url": url,
            "status_code": exc.code,
            "error": redact_text(body or str(exc)),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "provider": creds.name,
            "status": "request_error",
            "api_base": creds.api_base,
            "models_url": url,
            "error": redact_text(str(exc)),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }


def run_preflight(
    *,
    secret_path: Path | None,
    providers: list[str] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    config, loaded_path = load_secret_config(secret_path)
    profile_map = config.get("providers", {})
    if providers:
        selected = providers
    elif isinstance(profile_map, dict):
        selected = [str(name) for name, profile in profile_map.items() if isinstance(profile, dict) and profile.get("enabled", False)]
    else:
        selected = []
    results = [probe_provider(name.lower(), secret_path=loaded_path or secret_path, timeout=timeout) for name in selected]
    return {
        "schema_version": 1,
        "event": "provider_preflight",
        "checked_at": _utc_now(),
        "secret_profile": str(loaded_path) if loaded_path else None,
        "paid_fallback": False,
        "providers": results,
        "reachable_count": sum(item["status"] == "reachable" for item in results),
        "failure_count": sum(item["status"] != "reachable" for item in results),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--provider", action="append", dest="providers", default=None)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--out", type=Path, default=Path("runs/provider_preflight.json"))
    args = parser.parse_args(argv)
    try:
        result = run_preflight(
            secret_path=args.secrets,
            providers=args.providers,
            timeout=args.timeout,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"provider preflight failed: {redact_text(str(exc))}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
