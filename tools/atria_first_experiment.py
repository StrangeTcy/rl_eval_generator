#!/usr/bin/env python3
"""Prepare and run the bounded Atria Dawn Preview first-five pilot.

This runner deliberately has no model-catalog probe. Atria's documented model
ID is pinned in the profile and one bounded Chat Completions compatibility call
is the access gate. Local profile, inventory, generation, and oracle checks are
provider-free; a credential is required before the compatibility request.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.artifacts import write_json  # noqa: E402
from arena.docker_backend import DockerBackendError  # noqa: E402
from arena.providers import Completion, ProviderClient, ProviderError, require_https  # noqa: E402
from arena.secrets import redact_text, resolve_provider  # noqa: E402
from tools.atria_modality import inventory_selected_modalities  # noqa: E402
from tools.first_experiment import (  # noqa: E402
    EXPECTED_CASES,
    _generation_preflight,
    _runtime_check,
    _select_manifest,
)
from tools.oracle_preflight import validate_manifest_oracles  # noqa: E402
from tools.run_suite import run_suite  # noqa: E402
from tools.suite_inventory import _load_yaml  # noqa: E402

PROFILE_DEFAULT = ROOT / "experiments" / "atria_first5.yaml"
APPROVED_MODEL = "Atria-Dawn-Preview"
APPROVED_BASE = "https://api.atria-asi.ai/v1"
RATE_INTERVAL_SECONDS = 1.1
EXPECTED_LIMITS = {
    "max_steps": 20,
    "max_tokens": 8192,
    "invalid_retries": 1,
    "max_retries": 5,
    "max_http_attempts": 1207,
    "max_api_calls": 250,
    "max_wall_seconds": 7200,
    "floor_effect_after": 0,
    "sandbox": "docker",
}


def _write(path: Path, value: Any, *, secret: str | None = None) -> None:
    write_json(path, value, secret=secret)


def _validate_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Atria pilot profile not found: {path}")
    profile = _load_yaml(path)
    if profile.get("name") != "atria_first5":
        raise ValueError("Atria profile name must be atria_first5")
    if profile.get("provider") != "atria":
        raise ValueError("Atria profile provider must be atria")
    if profile.get("api_base") != APPROVED_BASE:
        raise ValueError(f"Atria api_base must be exactly {APPROVED_BASE}")
    require_https(str(profile["api_base"]))
    if profile.get("model") != APPROVED_MODEL:
        raise ValueError(f"Atria model must be exactly {APPROVED_MODEL}")
    if profile.get("api_key_env") != "ATRIA_API_KEY":
        raise ValueError("Atria profile must use ATRIA_API_KEY")
    if profile.get("concurrency") != 1 or profile.get("seed") != 0:
        raise ValueError("Atria pilot concurrency and seed must be exactly 1 and 0")
    if profile.get("temperature") != 1.0 or profile.get("top_p") != 0.95:
        raise ValueError("Atria pilot sampling must preserve temperature 1.0 and top_p 0.95")
    if profile.get("request_extra", {}) != {}:
        raise ValueError("Atria first pilot must not guess a reasoning request field")
    if profile.get("reasoning_mode") != "provider_default_uncontrolled":
        raise ValueError("Atria reasoning mode must be provider_default_uncontrolled")
    rate_limit = profile.get("rate_limit")
    if not isinstance(rate_limit, Mapping):
        raise ValueError("Atria profile rate_limit must be a mapping")
    if rate_limit.get("documented_requests_per_minute") != 60:
        raise ValueError("Atria documented request limit must be recorded as 60 RPM")
    if rate_limit.get("min_interval_seconds") != RATE_INTERVAL_SECONDS:
        raise ValueError("Atria minimum request interval must be 1.1 seconds")
    quota = profile.get("quota_ceiling_tokens")
    if quota is not None and (not isinstance(quota, int) or quota < 1):
        raise ValueError("quota_ceiling_tokens must be null or a positive integer")
    limits = profile.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError("Atria profile limits must be a mapping")
    for key, expected in EXPECTED_LIMITS.items():
        if limits.get(key) != expected:
            raise ValueError(f"Atria limit {key} must be exactly {expected!r}")
    cases = profile.get("cases")
    actual = []
    if not isinstance(cases, list):
        raise ValueError("Atria profile cases must be a list")
    for item in cases:
        if not isinstance(item, Mapping):
            raise ValueError("each Atria case must be a mapping")
        actual.append((item.get("environment"), item.get("difficulty")))
    if actual != EXPECTED_CASES:
        raise ValueError("Atria cases must match the existing five-case order exactly")
    if profile.get("stream") is not False:
        raise ValueError("Atria profile must explicitly set stream: false")
    return dict(profile)


def _optional_credentials(profile: Mapping[str, Any]) -> Any | None:
    try:
        return resolve_provider(
            "atria",
            api_key_env=str(profile["api_key_env"]),
            api_base=str(profile["api_base"]),
            require_key=True,
        )
    except ValueError as exc:
        if "No API key" in str(exc):
            return None
        raise


def _credential_check(credentials: Any | None) -> dict[str, Any]:
    if credentials is None:
        return {
            "credential_present": False,
            "provider": "atria",
            "source": None,
            "api_key_exposed": False,
        }
    source = str(getattr(credentials, "source", ""))
    return {
        "credential_present": bool(credentials.api_key),
        "provider": "atria",
        "source": "environment" if source.startswith("env:") else "profile",
        "api_key_exposed": False,
    }


def _compatibility_check(profile: Mapping[str, Any], credentials: Any, output: Path) -> dict[str, Any]:
    limits = profile["limits"]
    interval = float(profile["rate_limit"]["min_interval_seconds"])
    effective = {
        "provider": "atria",
        "api_base": profile["api_base"],
        "model": profile["model"],
        "messages": "compatibility_probe_v1",
        "max_tokens": 128,
        "temperature": profile["temperature"],
        "top_p": profile["top_p"],
        "stream": False,
        "request_extra": {},
        "reasoning_mode": profile["reasoning_mode"],
        "max_retries": limits["max_retries"],
        "max_attempts": int(limits["max_retries"]) + 1,
        "min_interval_seconds": interval,
    }
    client = ProviderClient(
        "atria",
        credentials.api_key,
        api_base=str(profile["api_base"]),
        max_retries=int(limits["max_retries"]),
        max_http_attempts=int(limits["max_retries"]) + 1,
        min_interval_seconds=interval,
    )
    try:
        completion: Completion = client.complete(
            model=str(profile["model"]),
            messages=[
                {"role": "system", "content": "Return a short compatibility acknowledgement."},
                {"role": "user", "content": "Reply with the single word READY."},
            ],
            max_tokens=128,
            temperature=float(profile["temperature"]),
            top_p=float(profile["top_p"]),
            request_extra={},
        )
    except ProviderError as exc:
        result = {
            "status": "failed",
            "effective_request": effective,
            "error_type": "provider_transient" if exc.retryable else type(exc).__name__,
            "status_code": exc.status_code,
            "request_id": exc.request_id,
            "response_headers": exc.response_headers,
            "attempts": exc.attempts,
            "retry_count": client.last_retry_count,
            "attempt_logs": client.last_attempt_logs,
            "diagnostic_body": redact_text(exc.body)[:2000],
        }
        _write(output, result, secret=credentials.api_key)
        return result
    attempts = client.http_attempts_used
    if (
        completion.status_code is None
        or not 200 <= completion.status_code < 300
        or completion.finish_reason != "stop"
        or not completion.content.strip()
        or not completion.usage
    ):
        result = {
            "status": "failed",
            "effective_request": effective,
            "error_type": "invalid_compatibility_completion",
            "requested_model": completion.requested_model,
            "resolved_model": completion.resolved_model,
            "request_id": completion.request_id,
            "response_headers": completion.response_headers,
            "provider": completion.provider,
            "upstream_provider": completion.upstream_provider,
            "status_code": completion.status_code,
            "finish_reason": completion.finish_reason,
            "usage": completion.usage,
            "content_length": len(completion.content),
            "reasoning_content_length": completion.reasoning_content_length,
            "elapsed_ms": completion.latency_ms,
            "latency_ms": completion.latency_ms,
            "attempts": attempts,
            "attempt_logs": client.last_attempt_logs,
            "retry_count": client.last_retry_count,
        }
        _write(output, result, secret=credentials.api_key)
        return result
    result = {
        "status": "passed",
        "effective_request": effective,
        "requested_model": completion.requested_model,
        "resolved_model": completion.resolved_model,
        "request_id": completion.request_id,
        "response_headers": completion.response_headers,
        "provider": completion.provider,
        "upstream_provider": completion.upstream_provider,
        "status_code": completion.status_code,
        "finish_reason": completion.finish_reason,
        "usage": completion.usage,
        "content_length": len(completion.content),
        "reasoning_content_length": completion.reasoning_content_length,
        "elapsed_ms": completion.latency_ms,
        "latency_ms": completion.latency_ms,
        "attempts": attempts,
        "attempt_logs": client.last_attempt_logs,
        "retry_count": client.last_retry_count,
    }
    _write(output, result, secret=credentials.api_key)
    return result


def _initial_checkpoint(
    manifest: Mapping[str, Any],
    profile: Mapping[str, Any],
    reason: str,
    *,
    quota_ceiling_tokens: int | None = None,
) -> dict[str, Any]:
    limits = profile["limits"]
    quota = (
        quota_ceiling_tokens
        if quota_ceiling_tokens is not None
        else profile.get("quota_ceiling_tokens")
    )
    return {
        "schema_version": 1,
        "manifest_case_count": manifest["case_count"],
        "run": {
            "manifest_commit": manifest.get("repository", {}).get("commit"),
            "provider": "atria",
            "model": profile["model"],
            "api_base": profile["api_base"],
            "sandbox": profile["limits"]["sandbox"],
            "api_key_env": profile["api_key_env"],
            "max_steps": limits["max_steps"],
            "max_tokens": limits["max_tokens"],
            "temperature": profile["temperature"],
            "top_p": profile["top_p"],
            "invalid_retries": limits["invalid_retries"],
            "max_retries": limits["max_retries"],
            "max_http_attempts": limits["max_http_attempts"],
            "max_api_calls": limits["max_api_calls"],
            "provider_min_interval_seconds": profile["rate_limit"]["min_interval_seconds"],
            "request_extra": {},
            "reasoning_mode": profile["reasoning_mode"],
            "quota_ceiling_tokens": quota,
        },
        "results": [],
        "paused": True,
        "pause_reason": reason,
    }


def _prepare_suite_checkpoint(
    path: Path,
    *,
    episode_http_budget: int,
    remaining_quota: int | None,
    secret: str,
) -> None:
    """Reconcile the pre-provider gate checkpoint with the live episode budget."""

    if not path.is_file():
        return
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    run = checkpoint.get("run")
    if not isinstance(run, dict):
        return
    run["max_http_attempts"] = episode_http_budget
    if remaining_quota is not None:
        run["max_tokens_total"] = remaining_quota
    _write(path, checkpoint, secret=secret)


def _usage_totals(records: list[Mapping[str, Any]]) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for record in records:
        usage = record.get("usage")
        if not isinstance(usage, Mapping):
            continue
        for key in totals:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] += int(value)
    if totals["total_tokens"] == 0:
        totals["total_tokens"] = totals["prompt_tokens"] + totals["completion_tokens"]
    return totals


def _actual_usage(output: Path, compatibility: Mapping[str, Any] | None = None) -> dict[str, Any]:
    episode_records: list[Mapping[str, Any]] = []
    for path in output.glob("episodes/**/model_responses.jsonl"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                value = json.loads(line)
                if isinstance(value, Mapping):
                    episode_records.append(value)
        except (OSError, ValueError):
            continue
    compatibility_usage = (
        compatibility.get("usage", {})
        if isinstance(compatibility, Mapping)
        else {}
    )
    compatibility_total = _usage_totals([{"usage": compatibility_usage}])
    episode_total = _usage_totals(episode_records)
    return {
        "compatibility": compatibility_total,
        "episodes": episode_total,
        "actual": {
            key: compatibility_total[key] + episode_total[key]
            for key in compatibility_total
        },
        "episode_response_records": len(episode_records),
    }


def _report(
    manifest: Mapping[str, Any],
    status: str,
    reason: str | None,
    checkpoint: Mapping[str, Any] | None,
    *,
    quota_ceiling_tokens: int | None = None,
    usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    results = list(checkpoint.get("results", [])) if checkpoint else []
    seen = {item.get("case_id") for item in results}
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "failure_policy": {
            "persistent_429_or_5xx": "provider_or_infrastructure_error_not_model_task_failure",
        },
        "provider": "atria",
        "model": APPROVED_MODEL,
        "theoretical_http_attempt_bound": 6 + 5 * 20 * 2 * 6,
        "configured_physical_attempt_ceiling": 1207,
        "operator_bounds": {
            "max_cases": 5,
            "max_api_calls_logical": 250,
            "episode_output_tokens_planning": 5 * 20 * 2 * 8192,
            "max_wall_seconds": 7200,
            "quota_ceiling_tokens": quota_ceiling_tokens,
        },
        "usage": dict(
            usage
            or {
                "compatibility": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "episodes": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "actual": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "episode_response_records": 0,
            }
        ),
        "case_results": results,
        "unfinished_cases": [
            {"case_id": case["case_id"], "environment": case["environment"], "reason": reason or "not_reached"}
            for case in manifest["cases"]
            if case["case_id"] not in seen
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=PROFILE_DEFAULT)
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("runs/atria_first5"))
    parser.add_argument(
        "--quota-ceiling-tokens",
        type=int,
        default=None,
        help="optional operator-supplied aggregate prompt-plus-completion token ceiling",
    )
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument(
        "--allow-compile-only-oracles", action="store_true",
        help="explicitly accept unverified judge behavior; otherwise block before any provider call",
    )
    args = parser.parse_args(argv)
    output = args.out.expanduser()
    try:
        profile_path = args.profile.expanduser().resolve()
        profile = _validate_profile(profile_path)
        if args.quota_ceiling_tokens is not None and args.quota_ceiling_tokens < 1:
            raise ValueError("quota-ceiling-tokens must be positive when provided")
        quota = (
            args.quota_ceiling_tokens
            if args.quota_ceiling_tokens is not None
            else profile.get("quota_ceiling_tokens")
        )
        manifest = _select_manifest(profile, profile_path)
        modality = inventory_selected_modalities(manifest, root=ROOT)
        manifest["pilot"]["modality_inventory"] = modality
        manifest["pilot"]["quota_ceiling_tokens"] = quota
        output.mkdir(parents=True, exist_ok=True)
        _write(output / "pilot_manifest.json", manifest)
        _write(output / "modality_inventory.json", modality)
        if not modality["all_selected_cases_text_only_compatible"]:
            reason = "unsupported_non_text_input_for_atria"
            checkpoint = _initial_checkpoint(
                manifest, profile, reason, quota_ceiling_tokens=quota
            )
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(output / "pilot_report.json", _report(
                manifest, "blocked", reason, checkpoint, quota_ceiling_tokens=quota
            ))
            print(f"Atria pilot blocked by explicit modality inventory; inspect {output}")
            return 2
        generation = _generation_preflight(manifest)
        _write(output / "generation_preflight.json", {"cases": generation})
        if any(item.get("status") != "ready" for item in generation):
            checkpoint = _initial_checkpoint(
                manifest, profile, "generation_preflight_failed", quota_ceiling_tokens=quota
            )
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(output / "pilot_report.json", _report(
                manifest,
                "blocked",
                "generation_preflight_failed",
                checkpoint,
                quota_ceiling_tokens=quota,
            ))
            print(f"Atria pilot prepared but blocked by generation preflight: {output}")
            return 2
        oracle = validate_manifest_oracles(manifest, root=ROOT)
        oracle["operator_compile_only_override"] = bool(
            args.allow_compile_only_oracles and not oracle.get("behavioral_coverage_complete", False)
        )
        _write(output / "oracle_preflight.json", oracle)
        oracle_reason = (
            "oracle_preflight_failed"
            if not oracle.get("model_sweep_allowed", False)
            else "behavioral_oracle_coverage_incomplete"
            if not oracle.get("behavioral_coverage_complete", False)
            and not args.allow_compile_only_oracles
            else None
        )
        if oracle_reason:
            checkpoint = _initial_checkpoint(
                manifest, profile, oracle_reason, quota_ceiling_tokens=quota
            )
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(output / "pilot_report.json", _report(
                manifest,
                "blocked",
                oracle_reason,
                checkpoint,
                quota_ceiling_tokens=quota,
            ))
            print(f"Atria pilot blocked before provider access: {oracle_reason}; inspect {output}")
            return 2
        runtime = _runtime_check()
        _write(output / "runtime.json", runtime)
        credentials = _optional_credentials(profile)
        _write(output / "credential_check.json", _credential_check(credentials))
        if credentials is None:
            reason = "waiting_for_private_ATRIA_API_KEY"
            checkpoint = _initial_checkpoint(
                manifest, profile, reason, quota_ceiling_tokens=quota
            )
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    "prepared",
                    reason,
                    checkpoint,
                    quota_ceiling_tokens=quota,
                ),
            )
            print("Atria pilot prepared with no provider call. Configure ATRIA_API_KEY privately.")
            print(f"Preparation artifacts: {output}")
            return 3
        if not runtime.get("available", False):
            reason = str(runtime.get("reason", "docker_unavailable"))
            checkpoint = _initial_checkpoint(
                manifest, profile, reason, quota_ceiling_tokens=quota
            )
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    "prepared",
                    reason,
                    checkpoint,
                    quota_ceiling_tokens=quota,
                ),
                secret=credentials.api_key,
            )
            print(f"Atria pilot prepared but Docker is unavailable; no provider call was made: {output}")
            return 4
        compatibility = _compatibility_check(profile, credentials, output / "compatibility.json")
        if compatibility.get("status") != "passed":
            reason = (
                "provider_infrastructure_error_compatibility"
                if compatibility.get("error_type") == "provider_transient"
                else "completion_compatibility_failed"
            )
            checkpoint = _initial_checkpoint(
                manifest, profile, reason, quota_ceiling_tokens=quota
            )
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    "paused",
                    reason,
                    checkpoint,
                    quota_ceiling_tokens=quota,
                ),
                secret=credentials.api_key,
            )
            print(f"Atria pilot paused after compatibility check; inspect {output}")
            return 7
        limits = profile["limits"]
        theoretical = int(limits["max_retries"]) + 1 + (
            len(manifest["cases"])
            * int(limits["max_steps"])
            * (1 + int(limits["invalid_retries"]))
            * (int(limits["max_retries"]) + 1)
        )
        compatibility_attempts = int(compatibility.get("attempts") or 0)
        episode_http_budget = int(limits["max_http_attempts"]) - compatibility_attempts
        if episode_http_budget < 1:
            raise ValueError("compatibility call exhausted the configured HTTP-attempt ceiling")
        if theoretical > int(limits["max_http_attempts"]):
            raise ValueError("Atria theoretical HTTP-attempt bound exceeds configured ceiling")
        compatibility_usage = _usage_totals(
            [{"usage": compatibility.get("usage", {})}]
        )["total_tokens"]
        remaining_quota = (
            int(quota) - compatibility_usage if quota is not None else None
        )
        if remaining_quota is not None and remaining_quota < 1:
            reason = "quota_ceiling_reached_by_compatibility_call"
            checkpoint = _initial_checkpoint(
                manifest, profile, reason, quota_ceiling_tokens=int(quota)
            )
            usage = _actual_usage(output, compatibility)
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    "paused",
                    reason,
                    checkpoint,
                    quota_ceiling_tokens=int(quota),
                    usage=usage,
                ),
                secret=credentials.api_key,
            )
            print(f"Atria pilot paused at the operator quota ceiling; inspect {output}")
            return 8
        pilot_started = time.monotonic()
        # The compatibility request consumed quota and rate-limit capacity.
        time.sleep(float(profile["rate_limit"]["min_interval_seconds"]))
        remaining_wall = max(0.1, int(limits["max_wall_seconds"]) - (time.monotonic() - pilot_started))
        _prepare_suite_checkpoint(
            output / "suite_checkpoint.json",
            episode_http_budget=episode_http_budget,
            remaining_quota=remaining_quota,
            secret=credentials.api_key,
        )
        checkpoint = run_suite(
            manifest,
            output_dir=output,
            provider="atria",
            model=APPROVED_MODEL,
            api_key_env="ATRIA_API_KEY",
            secrets=args.secrets,
            api_base=APPROVED_BASE,
            sandbox="docker",
            max_steps=int(limits["max_steps"]),
            max_tokens=int(limits["max_tokens"]),
            temperature=float(profile["temperature"]),
            top_p=float(profile["top_p"]),
            invalid_retries=int(limits["invalid_retries"]),
            max_retries=int(limits["max_retries"]),
            max_http_attempts=episode_http_budget,
            provider_min_interval_seconds=float(profile["rate_limit"]["min_interval_seconds"]),
            max_cases=5,
            max_api_calls=int(limits["max_api_calls"]),
            max_tokens_total=remaining_quota,
            max_wall_seconds=remaining_wall,
            min_interval_seconds=float(profile["rate_limit"]["min_interval_seconds"]),
            floor_effect_after=0,
            request_extra={},
            checkpoint_path=output / "suite_checkpoint.json",
            allow_compile_only_oracles=args.allow_compile_only_oracles,
            keep_images=args.keep_images,
            keep_workspace=args.keep_workspace,
        )
        status = "paused" if checkpoint.get("paused") else "completed"
        usage = _actual_usage(output, compatibility)
        report = _report(
            manifest,
            status,
            checkpoint.get("pause_reason"),
            checkpoint,
            quota_ceiling_tokens=quota,
            usage=usage,
        )
        report.update(
            {
                "compatibility_attempts": compatibility_attempts,
                "episode_http_attempt_ceiling": episode_http_budget,
                "theoretical_http_attempt_bound": theoretical,
                "configured_physical_attempt_ceiling": int(limits["max_http_attempts"]),
                "operator_bounds": {
                    "max_cases": 5,
                    "max_api_calls_logical": int(limits["max_api_calls"]),
                    "episode_output_tokens_planning": int(limits["max_steps"])
                    * (1 + int(limits["invalid_retries"]))
                    * len(manifest["cases"])
                    * int(limits["max_tokens"]),
                    "max_wall_seconds": int(limits["max_wall_seconds"]),
                    "quota_ceiling_tokens": quota,
                },
            }
        )
        _write(output / "pilot_report.json", report, secret=credentials.api_key)
        print(f"Atria pilot {status}; inspect {output}")
        return 0 if status == "completed" else 8
    except (OSError, RuntimeError, ValueError, DockerBackendError) as exc:
        print(f"atria_first_experiment failed: {redact_text(str(exc))}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
