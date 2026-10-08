#!/usr/bin/env python3
"""Run a bounded, provider-neutral model availability test.

This is deliberately not a ``/models`` check.  A number of hosted endpoints,
including Atria's, either do not expose a useful model list or do not promise
that a listed model is usable by the caller.  The only portable availability
check is a small completion against the exact model that a later workflow will
run.

The default series is three cheap requests:

1. an exact ``READY`` acknowledgement;
2. a small structured-output request tagged with the environment family; and
3. a minimal arena-action-shaped response.

The tool stops at the first failed request, never retries a failed probe by
default, and writes only bounded/redacted diagnostics.  It does not generate an
environment, start Docker, or run a paid evaluation episode.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.artifacts import write_json  # noqa: E402
from arena.providers import PROVIDERS, Completion, ProviderClient, ProviderError  # noqa: E402
from arena.secrets import redact_text, resolve_provider  # noqa: E402

SCHEMA_VERSION = 1
PROBE_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "ready_ack",
        "You are a model availability probe. Do not explain your reasoning.",
        "Reply with the single uppercase word READY.",
    ),
    (
        "family_tag",
        "You are checking whether this exact model can serve a small text request.",
        "Return one compact JSON object with exactly these fields: "
        '{"status":"READY","env_family":"ENV_FAMILY"}. Replace ENV_FAMILY '
        "with the supplied family name and output no markdown.",
    ),
    (
        "action_shape",
        "You are checking the JSON protocol used by an evaluation controller.",
        'Return one compact JSON object with type equal to "observe" and no other '
        "required fields. Do not call tools and do not write an explanation.",
    ),
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_content(value: str) -> str:
    return redact_text(value[:600]).strip()


def _usage(value: Mapping[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            result[str(key)] = int(item)
    return result


def _probe_messages(system: str, user: str, family: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user.replace("ENV_FAMILY", family)},
    ]


def _check_content(probe: str, content: str, family: str) -> tuple[bool, str]:
    stripped = content.strip()
    if not stripped:
        return False, "empty_completion"
    if probe == "ready_ack" and "READY" not in stripped.upper():
        return False, "ready_ack_missing"
    if probe == "family_tag":
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return False, "family_tag_not_json"
        if not isinstance(value, dict) or value.get("status") != "READY":
            return False, "family_tag_not_ready"
        if value.get("env_family") != family:
            return False, "family_tag_wrong_family"
    if probe == "action_shape":
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return False, "action_shape_not_json"
        if not isinstance(value, dict) or value.get("type") != "observe":
            return False, "action_shape_wrong_type"
    return True, "passed"


def run_model_preflight(
    *,
    provider: str,
    model: str,
    env_family: str,
    api_key_env: str | None = None,
    api_base: str | None = None,
    secrets: Path | None = None,
    out: Path | None = None,
    calls: int = 3,
    max_tokens: int = 32,
    reasoning_effort: str | None = None,
    min_interval_seconds: float = 0.0,
    max_retries: int = 0,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Probe ``model`` with a small bounded series and return an artifact."""

    provider = provider.strip().lower()
    model = model.strip()
    env_family = env_family.strip()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {sorted(PROVIDERS)}")
    if not model:
        raise ValueError("model must not be empty")
    if not env_family:
        raise ValueError("env_family must not be empty")
    if not 1 <= calls <= len(PROBE_SPECS):
        raise ValueError(f"calls must be between 1 and {len(PROBE_SPECS)}")
    if max_tokens < 1 or max_tokens > 256:
        raise ValueError("max_tokens must be between 1 and 256 for a cheap preflight")
    if max_retries < 0 or max_retries > 1:
        raise ValueError("max_retries must be 0 or 1 for a preflight")
    if min_interval_seconds < 0:
        raise ValueError("min_interval_seconds must not be negative")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    credentials = resolve_provider(
        provider,
        api_key_env=api_key_env,
        api_base=api_base,
        secret_path=secrets,
    )
    extra: dict[str, Any] = {}
    if reasoning_effort:
        extra["reasoning_effort"] = reasoning_effort
    client = ProviderClient(
        provider,
        credentials.api_key,
        api_base=credentials.api_base,
        timeout=timeout,
        max_retries=max_retries,
        max_http_attempts=calls * (max_retries + 1),
        min_interval_seconds=min_interval_seconds,
    )

    started = time.monotonic()
    probes: list[dict[str, Any]] = []
    for name, system, user in PROBE_SPECS[:calls]:
        probe_started = time.monotonic()
        record: dict[str, Any] = {
            "name": name,
            "status": "failed",
            "request": {
                "model": model,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
                "env_family": env_family,
            },
        }
        try:
            completion: Completion = client.complete(
                model=model,
                messages=_probe_messages(system, user, env_family),
                max_tokens=max_tokens,
                temperature=0.0,
                request_extra=extra,
            )
            passed, check = _check_content(name, completion.content, env_family)
            record.update(
                {
                    "status": "passed" if passed else "failed",
                    "check": check,
                    "status_code": completion.status_code,
                    "finish_reason": completion.finish_reason,
                    "requested_model": completion.requested_model,
                    "resolved_model": completion.resolved_model,
                    "provider": completion.provider,
                    "upstream_provider": completion.upstream_provider,
                    "request_id": completion.request_id,
                    "usage": _usage(completion.usage),
                    "reasoning_content_length": completion.reasoning_content_length,
                    "content_preview": _safe_content(completion.content),
                    "latency_ms": completion.latency_ms,
                    "attempts": client.last_http_attempts,
                }
            )
            if not passed:
                break
        except ProviderError as exc:
            record.update(
                {
                    "status": "failed",
                    "check": "provider_error",
                    "status_code": exc.status_code,
                    "request_id": exc.request_id,
                    "retryable": exc.retryable,
                    "attempts": exc.attempts,
                    "error_type": type(exc).__name__,
                    "diagnostic_body": redact_text(exc.body)[:600],
                    "attempt_logs": [
                        {
                            "attempt": item.get("attempt"),
                            "status_code": item.get("status_code"),
                            "error_type": item.get("error_type"),
                            "retryable": item.get("retryable"),
                        }
                        for item in client.last_attempt_logs[-3:]
                    ],
                }
            )
            break
        finally:
            record.setdefault(
                "elapsed_ms", max(0, int(round((time.monotonic() - probe_started) * 1000)))
            )
        probes.append(record)
        if record.get("status") != "passed":
            break

    passed = len(probes) == calls and all(item.get("status") == "passed" for item in probes)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event": "model_preflight",
        "checked_at": _utc_now(),
        "status": "ready" if passed else "unavailable",
        "provider": provider,
        "model": model,
        "api_base": credentials.api_base,
        "credential_source": "environment" if credentials.source.startswith("env:") else "profile",
        "api_key_exposed": False,
        "env_family": env_family,
        "reasoning_effort": reasoning_effort,
        "requested_calls": calls,
        "completed_calls": len(probes),
        "provider_http_attempts": client.http_attempts_used,
        "elapsed_ms": max(0, int(round((time.monotonic() - started) * 1000))),
        "probes": probes,
        "note": (
            "ready means the exact model answered every bounded protocol probe; "
            "it does not certify Docker, judge coverage, or task quality"
        ),
    }
    if out is not None:
        write_json(out, result, secret=credentials.api_key)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--env-family", required=True)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("runs/model_preflight.json"))
    parser.add_argument("--calls", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default=None)
    parser.add_argument("--min-interval-seconds", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_model_preflight(
            provider=args.provider,
            model=args.model,
            env_family=args.env_family,
            api_key_env=args.api_key_env,
            api_base=args.api_base,
            secrets=args.secrets,
            out=args.out,
            calls=args.calls,
            max_tokens=args.max_tokens,
            reasoning_effort=args.reasoning_effort,
            min_interval_seconds=args.min_interval_seconds,
            max_retries=args.max_retries,
            timeout=args.timeout,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "event": "model_preflight",
                    "status": "preflight_error",
                    "error_type": type(exc).__name__,
                    "detail": redact_text(str(exc))[:600],
                }
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
