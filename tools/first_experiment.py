#!/usr/bin/env python3
"""Prepare and, only when safe, run the bounded NVIDIA first five-case pilot.

This wrapper is deliberately thin: inventory, generation preflight, oracle
preflight, provider probing, episode execution, Docker isolation, and
checkpointing remain owned by the repository's existing tools.  It never asks
for a credential interactively and never accepts one as a command-line value.
Use ``tools/configure_provider.py`` or a private ``NVIDIA_API_KEY`` environment
variable before the live phase.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.artifacts import write_json  # noqa: E402
from arena.docker_backend import DockerBackend, DockerBackendError  # noqa: E402
from arena.providers import (  # noqa: E402
    Completion,
    ProviderClient,
    ProviderError,
    _validate_request_extra,
    require_https,
)
from arena.secrets import redact_text, resolve_provider  # noqa: E402
from tools.oracle_preflight import validate_manifest_oracles  # noqa: E402
from tools.provider_preflight import run_preflight  # noqa: E402
from tools.run_suite import run_suite  # noqa: E402
from tools.suite_inventory import (  # noqa: E402
    _load_yaml,
    _preflight_case,
    build_manifest,
)

PROFILE_DEFAULT = ROOT / "experiments" / "nim_first5.yaml"
EXPECTED_CASES = [
    ("regex_state_machine", "easy,easy"),
    ("epistemic_games", "trap,ambiguous,paired,balanced,bare_table"),
    ("categorical_lenses", "easy,easy"),
    ("rd_state_carry", "easy,easy,easy,easy,easy"),
    ("glyph", "easy,easy,easy,easy,easy,easy"),
]
REQUIRED_LIMITS = {
    "max_steps": 20,
    "max_tokens": 8192,
    "invalid_retries": 1,
    "max_retries": 0,
    "max_http_attempts": 250,
    "max_wall_seconds": 7200,
    "floor_effect_after": 0,
    "sandbox": "docker",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any, *, secret: str | None = None) -> None:
    write_json(path, value, secret=secret)


def _profile_has_credential(value: Any, trail: str = "profile") -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in {
                "api_key",
                "apikey",
                "authorization",
                "access_token",
                "refresh_token",
                "password",
                "token",
            }:
                raise ValueError(f"{trail} must not contain credential field {key!r}")
            _profile_has_credential(item, f"{trail}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _profile_has_credential(item, f"{trail}[{index}]")
    return False


def _validate_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"pilot profile not found: {path}")
    profile = _load_yaml(path)
    _profile_has_credential(profile)
    if profile.get("name") != "nim_first5":
        raise ValueError("pilot profile name must be nim_first5")
    if profile.get("provider") != "nvidia":
        raise ValueError("the first pilot is NVIDIA-only; provider switching is disabled")
    api_base = profile.get("api_base")
    if not isinstance(api_base, str) or not api_base:
        raise ValueError("pilot profile api_base must be a non-empty URL")
    require_https(api_base)
    model = profile.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("pilot profile model must be a non-empty exact model ID")
    if profile.get("api_key_env") != "NVIDIA_API_KEY":
        raise ValueError("pilot profile must use NVIDIA_API_KEY for private environment resolution")
    if profile.get("concurrency") != 1:
        raise ValueError("pilot concurrency must be exactly 1")
    if profile.get("seed") != 0:
        raise ValueError("pilot seed must be exactly 0")
    request_extra = profile.get("request_extra", {})
    _validate_request_extra(request_extra)
    limits = profile.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError("pilot profile limits must be a mapping")
    for key, expected in REQUIRED_LIMITS.items():
        if limits.get(key) != expected:
            raise ValueError(f"pilot limit {key} must be exactly {expected!r}")
    cases = profile.get("cases")
    if not isinstance(cases, list):
        raise ValueError("pilot profile cases must be a list")
    actual = []
    for item in cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("environment"), str):
            raise ValueError("each pilot case needs an environment and difficulty")
        if not isinstance(item.get("difficulty"), str):
            raise ValueError("each pilot difficulty must be a comma-separated string")
        actual.append((item["environment"], item["difficulty"]))
    if actual != EXPECTED_CASES:
        raise ValueError("pilot cases do not match the exact requested five-case order")
    return dict(profile)


def _select_manifest(profile: Mapping[str, Any], profile_path: Path) -> dict[str, Any]:
    """Inventory every config, then retain only the five pinned vectors."""

    manifest = build_manifest(root=ROOT, matrix="all", seeds=[0], dry_run=False)
    requested = list(EXPECTED_CASES)
    selected: list[dict[str, Any]] = []
    for environment, difficulty in requested:
        matches = [
            case
            for case in manifest["cases"]
            if case.get("environment") == environment
            and case.get("difficulty") == difficulty
            and case.get("seed") == 0
        ]
        if len(matches) != 1:
            raise ValueError(
                f"inventory did not contain exactly one requested case: {environment} {difficulty}"
            )
        selected.append(matches[0])
    environments_by_name = {
        item["environment"]: item for item in manifest.get("environments", [])
    }
    selected_environments = []
    for environment, _ in requested:
        if environment not in environments_by_name:
            raise ValueError(f"inventory did not contain requested environment {environment}")
        selected_environments.append(environments_by_name[environment])
    selected_manifest = dict(manifest)
    selected_manifest.update(
        {
            "case_count": len(selected),
            "environment_count": len(selected_environments),
            "cases": selected,
            "environments": selected_environments,
            "selection": {
                "matrix": "pilot",
                "profile": str(profile_path),
                "seeds": [0],
                "requested_cases": [
                    {"environment": environment, "difficulty": difficulty}
                    for environment, difficulty in requested
                ],
                "max_cases": 5,
            },
            "pilot": {
                "provider": profile["provider"],
                "model": profile["model"],
                "concurrency": profile["concurrency"],
                "profile_sha256": _sha256(profile_path),
                "config_hashes": {
                    case["environment"]: case["config_sha256"] for case in selected
                },
            },
        }
    )
    if not selected_manifest.get("ready_for_scheduler"):
        raise ValueError("inventory is not ready for the pilot; inspect registry/config issues")
    return selected_manifest


def _generation_preflight(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    results = []
    for case in manifest["cases"]:
        result = _preflight_case(dict(case), ROOT)
        results.append(
            {
                "case_id": case["case_id"],
                "environment": case["environment"],
                "difficulty": case["difficulty"],
                "seed": case["seed"],
                "config_sha256": case["config_sha256"],
                **result,
            }
        )
    return results


def _runtime_check() -> dict[str, Any]:
    executable = shutil.which("docker")
    if not executable:
        return {
            "sandbox": "docker",
            "available": False,
            "reason": "docker_executable_not_found",
        }
    try:
        version = DockerBackend().check_available()
    except DockerBackendError as exc:
        return {
            "sandbox": "docker",
            "available": False,
            "reason": "docker_server_unavailable",
            "detail": redact_text(str(exc))[-1000:],
        }
    return {"sandbox": "docker", "available": True, "executable": executable, "version": version}


def _optional_credentials(profile: Mapping[str, Any], secret_path: Path | None):
    try:
        return resolve_provider(
            "nvidia",
            api_key_env="NVIDIA_API_KEY",
            api_base=str(profile["api_base"]),
            secret_path=secret_path,
        )
    except ValueError as exc:
        message = str(exc)
        if "No API key" in message:
            return None
        raise


def _credential_check(credentials: Any) -> dict[str, Any]:
    if credentials is None:
        return {
            "credential_present": False,
            "provider": "nvidia",
            "source": None,
            "api_key_exposed": False,
        }
    source = str(getattr(credentials, "source", ""))
    return {
        "credential_present": bool(credentials.api_key),
        "provider": "nvidia",
        "source": "environment" if source.startswith("env:") else "profile",
        "api_key_exposed": False,
    }


def _initial_checkpoint(
    manifest: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    reason: str,
    secret_path: Path | None = None,
) -> dict[str, Any]:
    limits = profile["limits"]
    return {
        "schema_version": 1,
        "manifest_case_count": manifest["case_count"],
        "run": {
            "manifest_commit": manifest.get("repository", {}).get("commit"),
            "provider": "nvidia",
            "model": profile["model"],
            "api_base": profile["api_base"],
            "sandbox": "docker",
            "api_key_env": "NVIDIA_API_KEY",
            "secrets": str(secret_path) if secret_path else None,
            "max_steps": limits["max_steps"],
            "max_tokens": limits["max_tokens"],
            "invalid_retries": limits["invalid_retries"],
            "max_retries": limits["max_retries"],
            "request_extra": dict(profile.get("request_extra", {})),
            "max_tokens_total": None,
            "floor_effect_after": None,
            "reasoning_effort": None,
            "reasoning_enabled": False,
            "estimated_case_api_calls": limits["max_steps"] * (1 + limits["invalid_retries"]),
            "estimated_case_output_tokens": limits["max_steps"]
            * (1 + limits["invalid_retries"])
            * limits["max_tokens"],
        },
        "results": [],
        "paused": True,
        "pause_reason": reason,
        "floor_effect": False,
        "floor_effect_streak": 0,
    }


def _report(
    manifest: Mapping[str, Any],
    *,
    status: str,
    reason: str | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    unfinished_reason: str | None = None,
) -> dict[str, Any]:
    results = list(checkpoint.get("results", [])) if checkpoint else []
    seen = {item.get("case_id") for item in results}
    unfinished = []
    for case in manifest["cases"]:
        if case["case_id"] not in seen:
            unfinished.append(
                {
                    "case_id": case["case_id"],
                    "environment": case["environment"],
                    "reason": unfinished_reason or reason or "not_reached",
                }
            )
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "provider": "nvidia",
        "model": manifest.get("pilot", {}).get("model"),
        "manifest_commit": manifest.get("repository", {}).get("commit"),
        "config_hashes": manifest.get("pilot", {}).get("config_hashes", {}),
        "case_results": [
            {
                key: item.get(key)
                for key in (
                    "case_id",
                    "environment",
                    "difficulty",
                    "seed",
                    "status",
                    "verdict",
                    "score",
                    "failure_mode",
                    "error",
                    "elapsed_seconds",
                )
                if key in item
            }
            for item in results
        ],
        "unfinished_cases": unfinished,
    }


def _compatibility_check(
    profile: Mapping[str, Any],
    credentials: Any,
    output: Path,
) -> dict[str, Any]:
    limits = profile["limits"]
    request_extra = dict(profile.get("request_extra", {}))
    effective = {
        "provider": "nvidia",
        "api_base": profile["api_base"],
        "model": profile["model"],
        "messages": "compatibility_probe_v1",
        "max_tokens": min(64, int(limits["max_tokens"])),
        "temperature": 0.0,
        "request_extra": request_extra,
        "max_retries": limits["max_retries"],
    }
    client = ProviderClient(
        "nvidia",
        credentials.api_key,
        api_base=str(profile["api_base"]),
        max_retries=int(limits["max_retries"]),
    )
    try:
        completion: Completion = client.complete(
            model=str(profile["model"]),
            messages=[
                {"role": "system", "content": "Return a short compatibility acknowledgement."},
                {"role": "user", "content": "Reply with the single word READY."},
            ],
            max_tokens=effective["max_tokens"],
            temperature=0.0,
            request_extra=request_extra,
        )
    except ProviderError as exc:
        failure = {
            "status": "failed",
            "effective_request": effective,
            "error_type": type(exc).__name__,
            "status_code": exc.status_code,
            "request_id": exc.request_id,
            "attempts": exc.attempts,
            "retry_count": client.last_retry_count,
            "diagnostic_body": redact_text(exc.body)[:2000],
        }
        _write(output, failure, secret=credentials.api_key)
        return failure
    result = {
        "status": "passed",
        "effective_request": effective,
        "requested_model": completion.requested_model,
        "resolved_model": completion.resolved_model,
        "finish_reason": completion.finish_reason,
        "usage": completion.usage,
        "response_chars": len(completion.content),
        "response_sha256": hashlib.sha256(completion.content.encode("utf-8")).hexdigest(),
        "attempts": len(client.last_attempts) + 1,
        "retry_count": client.last_retry_count,
    }
    _write(output, result, secret=credentials.api_key)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=PROFILE_DEFAULT)
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("runs/nim_first5"))
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.out.expanduser()
    try:
        profile_path = args.profile.expanduser().resolve()
        profile = _validate_profile(profile_path)
        if args.secrets is not None:
            secret_path = args.secrets.expanduser().resolve()
            if not secret_path.is_file():
                raise ValueError(f"specified secret profile not found: {secret_path}")
        else:
            secret_path = None
        manifest = _select_manifest(profile, profile_path)
        output.mkdir(parents=True, exist_ok=True)
        _write(output / "pilot_manifest.json", manifest)
        generation = _generation_preflight(manifest)
        _write(output / "generation_preflight.json", {"cases": generation})
        if any(item.get("status") != "ready" for item in generation):
            checkpoint = _initial_checkpoint(manifest, profile, reason="generation_preflight_failed", secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="blocked",
                    reason="generation_preflight_failed",
                    checkpoint=checkpoint,
                    unfinished_reason="generation_preflight_failed",
                ),
            )
            print(f"Pilot prepared but blocked by generation preflight; inspect {output}")
            return 2
        oracle = validate_manifest_oracles(manifest, root=ROOT)
        _write(output / "oracle_preflight.json", oracle)
        if not oracle.get("model_sweep_allowed", False):
            checkpoint = _initial_checkpoint(manifest, profile, reason="oracle_preflight_failed", secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="blocked",
                    reason="oracle_preflight_failed",
                    checkpoint=checkpoint,
                    unfinished_reason="oracle_preflight_failed",
                ),
            )
            print(f"Pilot prepared but blocked by oracle preflight; inspect {output}")
            return 2
        runtime = _runtime_check()
        _write(output / "runtime.json", runtime)
        credentials = _optional_credentials(profile, secret_path)
        _write(output / "credential_check.json", _credential_check(credentials))
        if manifest.get("repository", {}).get("dirty"):
            reason = "dirty_worktree; commit the pinned profile/code before live execution"
            checkpoint = _initial_checkpoint(manifest, profile, reason=reason, secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(
                output / "pilot_report.json",
                _report(manifest, status="blocked", reason=reason, checkpoint=checkpoint),
            )
            print(f"Pilot prepared but live execution requires a clean checkout; inspect {output}")
            return 2
        if credentials is None:
            reason = "waiting_for_private_NVIDIA_API_KEY"
            checkpoint = _initial_checkpoint(manifest, profile, reason=reason, secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="prepared",
                    reason=reason,
                    checkpoint=checkpoint,
                    unfinished_reason="credential_missing",
                ),
            )
            print(
                "Pilot prepared with no provider call. Set NVIDIA_API_KEY privately or use "
                "tools/configure_provider.py; do not paste a credential into chat."
            )
            print(f"Preparation artifacts: {output}")
            return 3
        if not runtime.get("available", False):
            reason = str(runtime.get("reason", "docker_unavailable"))
            checkpoint = _initial_checkpoint(manifest, profile, reason=reason, secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="prepared",
                    reason=reason,
                    checkpoint=checkpoint,
                    unfinished_reason="docker_unavailable",
                ),
                secret=credentials.api_key,
            )
            print(f"Pilot prepared but Docker is unavailable; no provider call was made: {output}")
            return 4
        pilot_started = time.monotonic()
        preflight = run_preflight(secret_path=secret_path, providers=["nvidia"])
        _write(output / "provider_preflight.json", preflight, secret=credentials.api_key)
        provider_result = next(
            (item for item in preflight.get("providers", []) if item.get("provider") == "nvidia"),
            None,
        )
        if not provider_result or provider_result.get("status") != "reachable":
            reason = "provider_preflight_failed"
            checkpoint = _initial_checkpoint(manifest, profile, reason=reason, secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="paused",
                    reason=reason,
                    checkpoint=checkpoint,
                    unfinished_reason="provider_preflight_failed",
                ),
                secret=credentials.api_key,
            )
            print(f"Pilot paused after provider preflight; inspect {output}")
            return 5
        model_ids = provider_result.get("model_ids", [])
        if profile["model"] not in model_ids:
            reason = "configured_model_not_confirmed_by_preflight"
            checkpoint = _initial_checkpoint(manifest, profile, reason=reason, secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="paused",
                    reason=reason,
                    checkpoint=checkpoint,
                    unfinished_reason=reason,
                ),
                secret=credentials.api_key,
            )
            print(f"Pilot paused: exact configured model was not confirmed by /models; inspect {output}")
            return 6
        compatibility = _compatibility_check(profile, credentials, output / "compatibility.json")
        if compatibility.get("status") != "passed":
            reason = "completion_compatibility_failed"
            checkpoint = _initial_checkpoint(manifest, profile, reason=reason, secret_path=secret_path)
            _write(output / "suite_checkpoint.json", checkpoint, secret=credentials.api_key)
            _write(
                output / "pilot_report.json",
                _report(
                    manifest,
                    status="paused",
                    reason=reason,
                    checkpoint=checkpoint,
                    unfinished_reason=reason,
                ),
                secret=credentials.api_key,
            )
            print(f"Pilot paused after bounded completion check; inspect {output}")
            return 7
        limits = profile["limits"]
        episode_calls = int(limits["max_steps"]) * (1 + int(limits["invalid_retries"]))
        http_budget = 2 + len(manifest["cases"]) * episode_calls * (1 + int(limits["max_retries"]))
        if http_budget > int(limits["max_http_attempts"]):
            raise ValueError("pilot HTTP-attempt budget exceeds the configured maximum")
        remaining_wall_seconds = max(
            0.1,
            float(limits["max_wall_seconds"]) - (time.monotonic() - pilot_started),
        )
        checkpoint = run_suite(
            manifest,
            output_dir=output,
            provider="nvidia",
            model=str(profile["model"]),
            api_key_env="NVIDIA_API_KEY",
            secrets=secret_path,
            api_base=str(profile["api_base"]),
            sandbox="docker",
            max_steps=int(limits["max_steps"]),
            max_tokens=int(limits["max_tokens"]),
            invalid_retries=int(limits["invalid_retries"]),
            max_retries=int(limits["max_retries"]),
            max_cases=5,
            max_api_calls=250,
            max_wall_seconds=remaining_wall_seconds,
            floor_effect_after=0,
            request_extra=dict(profile.get("request_extra", {})),
            checkpoint_path=output / "suite_checkpoint.json",
            keep_images=args.keep_images,
            keep_workspace=args.keep_workspace,
        )
        status = "paused" if checkpoint.get("paused") else "completed"
        _write(
            output / "pilot_report.json",
            {
                **_report(manifest, status=status, reason=checkpoint.get("pause_reason"), checkpoint=checkpoint),
                "http_attempt_budget": {
                    "provider_preflight_models": 1,
                    "compatibility": 1,
                    "episode_completion_calls": episode_calls * len(manifest["cases"]),
                    "max_retries": int(limits["max_retries"]),
                    "worst_case_attempts": http_budget,
                    "configured_max": int(limits["max_http_attempts"]),
                },
            },
            secret=credentials.api_key,
        )
        print(f"Pilot {status}; inspect {output}")
        return 0 if status == "completed" else 8
    except (OSError, RuntimeError, ValueError, DockerBackendError) as exc:
        print(f"first_experiment failed: {redact_text(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
