#!/usr/bin/env python3
"""Probe enabled OpenAI-compatible provider profiles without logging keys."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.providers import open_no_redirect, provider_auth_headers, require_https  # noqa: E402
from arena.secrets import load_secret_config, redact_text, resolve_provider  # noqa: E402


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _models_url(base: str) -> str:
    require_https(base)
    return base.rstrip("/") + "/models"


def _headers(provider: str, key: str) -> dict[str, str]:
    value = {
        **provider_auth_headers(provider, key),
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


def _request_id(headers: Mapping[str, Any] | None) -> str | None:
    for key, value in (headers or {}).items():
        if str(key).lower() in {"x-request-id", "request-id", "openrouter-request-id"}:
            return str(value)
    return None


def classify_status(status_code: int | None, error_code: str | None = None) -> str:
    """Name the condition a status code describes, keeping auth and quota apart.

    The distinction is the whole point of probing: ``401`` means the credential is
    not accepted, while ``429`` means it was accepted and the account cannot be
    billed. Both stop a pilot, and confusing them turns one into the other.
    """

    if error_code == "invalid_api_key":
        return "credential_rejected"
    if status_code in (401, 403):
        return "credential_rejected"
    if status_code == 429:
        return "quota_or_rate_limited"
    if status_code is None:
        return "transport_error"
    if 200 <= status_code < 300:
        return "authenticated"
    if status_code == 404:
        # Reached routing, so the key was accepted; only the path is missing.
        return "authenticated_endpoint_absent"
    return "reachable" if status_code == 200 else f"http_status_{status_code}"


# Exit codes so a workflow can branch on the verdict instead of parsing JSON.
EXIT_AUTHENTICATED = 0
EXIT_USAGE = 2
EXIT_CREDENTIAL_REJECTED = 3
EXIT_QUOTA = 4
EXIT_NO_VERDICT = 5
EXIT_NO_CREDENTIAL = 6

_CLASSIFICATION_EXIT = {
    "credential_rejected": EXIT_CREDENTIAL_REJECTED,
    "quota_or_rate_limited": EXIT_QUOTA,
    "authenticated": EXIT_AUTHENTICATED,
    "authenticated_endpoint_absent": EXIT_AUTHENTICATED,
    "no_credential": EXIT_NO_CREDENTIAL,
}


def classify_exit(classification: str) -> int:
    """Map a classification onto the process exit code used by the workflow."""

    return _CLASSIFICATION_EXIT.get(classification, EXIT_NO_VERDICT)


def _error_code(body: str) -> str | None:
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if isinstance(payload, Mapping):
        err = payload.get("error")
        if isinstance(err, Mapping) and isinstance(err.get("code"), str):
            return err["code"]
        if isinstance(payload.get("code"), str):
            return payload["code"]
    return None


def _sanitize(value: Any) -> Any:
    """Redact every serialized string as a final defense-in-depth pass."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {redact_text(str(key)): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def probe_provider(
    name: str,
    *,
    secret_path: Path | None,
    timeout: float,
    api_base: str | None = None,
    api_key_env: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        creds = resolve_provider(
            name,
            api_base=api_base,
            api_key_env=api_key_env,
            secret_path=secret_path,
        )
        url = _models_url(creds.api_base)
    except (OSError, ValueError):
        return {
            "provider": name,
            "status": "credential_error",
            "status_code": None,
            "classification": "no_credential",
            "error_type": "credential_or_endpoint_error",
            "model_ids": [],
            "latency_ms": round((time.monotonic() - started) * 1000),
        }

    try:
        req = request.Request(url, headers=_headers(creds.name, creds.api_key), method="GET")
        # The authenticated opener rejects every redirect. In particular, it
        # never copies Authorization to a different origin or downgraded URL.
        with open_no_redirect(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
            request_id = _request_id(getattr(response, "headers", None))
        payload = json.loads(body)
        model_ids = _extract_models(payload)
        code = _error_code(body)
        result = {
            "provider": creds.name,
            "status": "reachable",
            "status_code": status_code,
            "classification": classify_status(status_code, code),
            "model_ids": model_ids,
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        if code is not None:
            result["error_code"] = code
        if request_id is not None:
            result["request_id"] = request_id
        return result
    except error.HTTPError as exc:
        body = ""
        try:
            body = (exc.read() or b"").decode("utf-8", errors="replace")
        except OSError:
            body = ""
        code = _error_code(body)
        result = {
            "provider": creds.name,
            "status": "http_error",
            "status_code": int(exc.code),
            "classification": classify_status(int(exc.code), code),
            "error_code": code,
            "error_type": "http_error",
            "model_ids": [],
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        request_id = _request_id(exc.headers)
        if request_id is not None:
            result["request_id"] = request_id
        return result
    except json.JSONDecodeError:
        return {
            "provider": creds.name,
            "status": "invalid_response",
            "status_code": None,
            "classification": "transport_error",
            "error_type": "invalid_json",
            "model_ids": [],
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
    except (OSError, TimeoutError, ValueError):
        return {
            "provider": creds.name,
            "status": "request_error",
            "status_code": None,
            "classification": "transport_error",
            "error_type": "request_error",
            "model_ids": [],
            "latency_ms": round((time.monotonic() - started) * 1000),
        }


def run_preflight(
    *,
    secret_path: Path | None,
    providers: list[str] | None = None,
    timeout: float = 20.0,
    api_base: str | None = None,
    api_key_env: str | None = None,
) -> dict[str, Any]:
    config, loaded_path = load_secret_config(secret_path)
    profile_map = config.get("providers", {})
    if providers:
        selected = providers
    elif isinstance(profile_map, dict):
        selected = [
            str(name)
            for name, profile in profile_map.items()
            if isinstance(profile, dict) and profile.get("enabled", False)
        ]
    else:
        selected = []
    results = [
        probe_provider(
            name.lower(),
            secret_path=loaded_path or secret_path,
            timeout=timeout,
            api_base=api_base,
            api_key_env=api_key_env,
        )
        for name in selected
    ]
    # One verdict for the run, chosen by severity so a refused credential never
    # hides behind a reachable one.
    classifications = [str(item.get("classification", "no_verdict")) for item in results]
    for candidate in ("credential_rejected", "quota_or_rate_limited", "no_credential"):
        if candidate in classifications:
            verdict = candidate
            break
    else:
        verdict = "authenticated" if classifications and all(
            c.startswith("authenticated") for c in classifications
        ) else "no_verdict"
    return _sanitize(
        {
            "schema_version": 1,
            "event": "provider_preflight",
            "checked_at": _utc_now(),
            "paid_fallback": False,
            "providers": results,
            "verdict": verdict,
            "exit_code": classify_exit(verdict),
            "reachable_count": sum(item["status"] == "reachable" for item in results),
            "failure_count": sum(item["status"] != "reachable" for item in results),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--provider", action="append", dest="providers", default=None)
    parser.add_argument("--api-base", default=None, help="override the provider profile base")
    parser.add_argument("--api-key-env", default=None, help="read the key from this variable")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--out", type=Path, default=Path("runs/provider_preflight.json"))
    parser.add_argument(
        "--github",
        action="store_true",
        help="emit the verdict as a run-page annotation on stdout",
    )
    args = parser.parse_args(argv)
    try:
        result = run_preflight(
            secret_path=args.secrets,
            providers=args.providers,
            timeout=args.timeout,
            api_base=args.api_base,
            api_key_env=args.api_key_env,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "event": "provider_preflight",
                    "status": "preflight_error",
                    "error_type": type(exc).__name__,
                }
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    verdict = str(result["verdict"])
    if args.github:
        # Annotations are only parsed when they reach stdout. The verdict names the
        # layer: an auth refusal is not a model result, and a quota refusal is not
        # an auth result.
        print(f"::notice title=provider preflight::{verdict}")
    return int(result.get("exit_code", EXIT_NO_VERDICT)) if verdict != "authenticated" else 0


if __name__ == "__main__":
    raise SystemExit(main())
