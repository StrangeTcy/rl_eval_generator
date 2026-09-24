#!/usr/bin/env python3
"""Run a checkpointed suite manifest through the existing arena controller.

The scheduler is intentionally provider-neutral.  It launches one
``arena.py run`` process per manifest case, keeps the API key in the controller
process environment, and never passes a literal key to Docker or an agent
command.  A model failure is a scored result and does not stop the suite;
provider/quota and infrastructure failures pause the run so a free allowance
is not consumed by blind retries.

The manifest is the experiment contract.  Build one first with
``tools/suite_inventory.py`` and do not change provider/model/protocol halfway
through a checkpoint.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.secrets import resolve_provider  # noqa: E402

PROVIDER_MARKERS = (
    "429",
    "503",
    "504",
    "rate limit",
    "rate_limit",
    "quota",
    "insufficient_quota",
    "too many requests",
    "api key",
    "unauthorized",
    "authentication",
    "credit",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._=-" else "_" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _extract_result(text: str) -> dict[str, Any] | None:
    """Extract the largest JSON object containing a run result."""

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    scored = [item for item in candidates if "final" in item or "run_dir" in item]
    return max(scored or candidates, key=lambda item: len(json.dumps(item))) if candidates else None


def _redact(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[-4000:]


def _provider_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in PROVIDER_MARKERS)


def _current_config_hash(root: Path, case: dict[str, Any]) -> str | None:
    path = root / str(case.get("config_path", ""))
    if not path.is_file():
        return None
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _estimated_case_budget(max_steps: int, max_tokens: int, invalid_retries: int) -> tuple[int, int]:
    if max_steps < 1 or max_tokens < 1 or invalid_retries < 0:
        raise ValueError("max-steps and max-tokens must be positive; invalid-retries must not be negative")
    calls = max_steps * (1 + invalid_retries)
    return calls, calls * max_tokens


def _is_zero_score(result: dict[str, Any]) -> bool:
    score = result.get("score")
    return result.get("status") == "scored" and isinstance(score, (int, float)) and float(score) == 0.0


def _load_checkpoint(path: Path, *, manifest: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if path.is_file():
        checkpoint = _read_json(path)
        previous = checkpoint.get("run", {})
        immutable = (
            "manifest_commit",
            "provider",
            "model",
            "api_base",
            "sandbox",
            "secrets",
            "max_steps",
            "max_tokens",
            "temperature",
            "top_p",
            "invalid_retries",
            "max_retries",
            "max_http_attempts",
            "provider_min_interval_seconds",
            "max_api_calls",
            "request_extra",
            "max_tokens_total",
            "floor_effect_after",
            "reasoning_effort",
        )
        for field in immutable:
            if field == "max_http_attempts" and previous.get(field) is None:
                # A preflight checkpoint may intentionally leave the live
                # episode allocation unset until compatibility has consumed its
                # bounded attempts.
                continue
            if previous.get(field) != metadata.get(field):
                raise ValueError(
                    f"checkpoint metadata mismatch for {field}: "
                    f"{previous.get(field)!r} != {metadata.get(field)!r}"
                )
        if checkpoint.get("manifest_case_count") != manifest.get("case_count"):
            raise ValueError("manifest case count changed; use a new checkpoint")
        return checkpoint
    return {
        "schema_version": 1,
        "run": metadata,
        "manifest_case_count": manifest.get("case_count", len(manifest.get("cases", []))),
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "paused": False,
        "pause_reason": None,
        "floor_effect": False,
        "floor_effect_streak": 0,
        "results": [],
    }


def _result_by_case(checkpoint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["case_id"]): item for item in checkpoint.get("results", []) if item.get("case_id")}


def _coverage_rows(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in checkpoint.get("results", [])]


def _write_coverage(output_dir: Path, checkpoint: dict[str, Any]) -> None:
    rows = _coverage_rows(checkpoint)
    coverage_json = output_dir / "coverage.json"
    _write_json_atomic(
        coverage_json,
        {
            "schema_version": 1,
            "run": checkpoint.get("run", {}),
            "updated_at": checkpoint.get("updated_at"),
            "paused": checkpoint.get("paused", False),
            "pause_reason": checkpoint.get("pause_reason"),
            "floor_effect": checkpoint.get("floor_effect", False),
            "floor_effect_streak": checkpoint.get("floor_effect_streak", 0),
            "counts": {
                status: sum(row.get("status") == status for row in rows)
                for status in sorted({str(row.get("status")) for row in rows})
            },
            "rows": rows,
        },
    )
    fields = [
        "case_id",
        "environment",
        "track",
        "difficulty",
        "seed",
        "status",
        "verdict",
        "score",
        "failure_mode",
        "returncode",
        "elapsed_seconds",
        "http_attempts",
        "http_attempt_ceiling",
        "run_dir",
        "error",
    ]
    with (output_dir / "coverage.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)
    lines = [
        "# Suite coverage",
        "",
        f"- Cases in manifest: `{checkpoint.get('manifest_case_count', 0)}`",
        f"- Cases recorded: `{len(rows)}`",
        f"- Paused: `{checkpoint.get('paused', False)}`",
        f"- Pause reason: `{checkpoint.get('pause_reason') or 'none'}`",
        f"- Floor effect: `{checkpoint.get('floor_effect', False)}`",
        "",
        "| environment | difficulty | seed | status | verdict | score | runtime (s) |",
        "|---|---|---:|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('environment')} | {row.get('difficulty')} | {row.get('seed')} | "
            f"{row.get('status')} | {row.get('verdict', '')} | {row.get('score', '')} | "
            f"{row.get('elapsed_seconds', '')} |"
        )
    (output_dir / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_command(
    case: dict[str, Any],
    *,
    provider: str,
    model: str,
    api_key_env: str,
    secrets: Path | None,
    api_base: str | None,
    sandbox: str,
    output_dir: Path,
    max_steps: int,
    max_tokens: int,
    invalid_retries: int,
    keep_images: bool,
    keep_workspace: bool,
    temperature: float = 0.0,
    top_p: float | None = None,
    max_http_attempts: int | None = None,
    provider_min_interval_seconds: float = 0.0,
    max_retries: int = 3,
    reasoning_effort: str | None = None,
    request_extra: dict[str, Any] | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "arena.py"),
        "run",
        "--provider",
        provider,
        "--model",
        model,
        "--api-key-env",
        api_key_env,
    ]
    if secrets:
        command.extend(["--secrets", str(secrets)])
    command.extend([
        "--env",
        str(case["environment"]),
        "--difficulty",
        str(case["difficulty"]),
        "--seed",
        str(case["seed"]),
        "--max-steps",
        str(max_steps),
        "--max-tokens",
        str(max_tokens),
        "--temperature",
        str(temperature),
        "--invalid-retries",
        str(invalid_retries),
        "--max-retries",
        str(max_retries),
    ])
    if top_p is not None:
        command.extend(["--top-p", str(top_p)])
    if max_http_attempts is not None:
        command.extend(["--max-http-attempts", str(max_http_attempts)])
    if provider_min_interval_seconds > 0:
        command.extend(
            ["--provider-min-interval-seconds", str(provider_min_interval_seconds)]
        )
    command.extend([
        "--sandbox",
        sandbox,
        "--out",
        str(output_dir),
    ])
    if api_base:
        command.extend(["--api-base", api_base])
    effective_extra = dict(request_extra or {})
    if reasoning_effort:
        effective_extra["reasoning"] = {"effort": reasoning_effort}
    if effective_extra:
        command.extend(
            [
                "--request-extra",
                json.dumps(effective_extra, separators=(",", ":")),
            ]
        )
    if keep_images:
        command.append("--keep-images")
    if keep_workspace:
        command.append("--keep-workspace")
    return command


def run_suite(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    provider: str,
    model: str,
    api_key_env: str,
    secrets: Path | None = None,
    api_base: str | None = None,
    sandbox: str = "docker",
    max_steps: int = 30,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    top_p: float | None = None,
    invalid_retries: int = 2,
    max_retries: int = 3,
    max_http_attempts: int | None = None,
    provider_min_interval_seconds: float = 0.0,
    max_cases: int | None = None,
    max_api_calls: int | None = None,
    max_output_tokens: int | None = None,
    max_tokens_total: int | None = None,
    max_wall_seconds: float | None = None,
    min_interval_seconds: float = 0.0,
    floor_effect_after: int | None = 3,
    reasoning_effort: str | None = None,
    request_extra: dict[str, Any] | None = None,
    checkpoint_path: Path | None = None,
    dry_run: bool = False,
    allow_config_drift: bool = False,
    retry_recorded: bool = False,
    keep_images: bool = False,
    keep_workspace: bool = False,
) -> dict[str, Any]:
    if not manifest.get("ready_for_scheduler", False) and not allow_config_drift:
        raise ValueError("manifest is not ready; fix inventory issues or pass --allow-config-drift explicitly")
    if not provider or not model:
        raise ValueError("provider and model are required")
    if invalid_retries < 0 or max_retries < 0 or max_retries > 5:
        raise ValueError("invalid-retries must not be negative and max-retries must be between 0 and 5")
    if top_p is not None and not 0.0 < top_p <= 1.0:
        raise ValueError("top-p must be greater than 0 and at most 1")
    if max_http_attempts is not None and max_http_attempts < 1:
        raise ValueError("max-http-attempts must be positive when provided")
    if provider_min_interval_seconds < 0:
        raise ValueError("provider-min-interval-seconds must not be negative")
    if not api_key_env and not dry_run:
        raise ValueError("api_key_env is required; do not pass a literal API key to the scheduler")
    if max_tokens_total is not None and max_tokens_total < 1:
        raise ValueError("max-tokens-total must be positive")
    if max_output_tokens is not None and max_output_tokens < 1:
        raise ValueError("max-output-tokens must be positive")
    if floor_effect_after is not None and floor_effect_after < 0:
        raise ValueError("floor-effect-after must be positive, zero, or omitted")
    if floor_effect_after == 0:
        floor_effect_after = None
    if sandbox != "docker":
        raise ValueError("suite scheduler requires Docker isolation; use a separate local smoke test")
    output_dir.mkdir(parents=True, exist_ok=True)
    oracle_report: dict[str, Any] | None = None
    if not dry_run:
        # This gate is intentionally local and provider-free.  It validates the
        # pinned environment/reference behavior before resolving credentials or
        # starting the first model request.
        from tools.oracle_preflight import validate_manifest_oracles

        oracle_report = validate_manifest_oracles(manifest, root=ROOT)
        _write_json_atomic(output_dir / "oracle_preflight.json", oracle_report)
        if not oracle_report.get("model_sweep_allowed", False):
            raise ValueError(
                "zero-API oracle preflight failed; inspect "
                f"{output_dir / 'oracle_preflight.json'} before retrying"
            )
    checkpoint_path = checkpoint_path or output_dir / "suite_checkpoint.json"
    repository = manifest.get("repository", {})
    selection = manifest.get("selection", {})
    matrix = selection.get("matrix") if isinstance(selection, dict) else None
    if matrix == "all" and not dry_run and max_tokens_total is None and max_output_tokens is None:
        raise ValueError(
            "all-matrix execution requires --dry-run or an explicit "
            "--max-tokens-total/--max-output-tokens ceiling"
        )
    case_budget_calls, case_budget_tokens = _estimated_case_budget(
        max_steps, max_tokens, invalid_retries
    )
    metadata = {
        "manifest_commit": repository.get("commit"),
        "provider": provider,
        "model": model,
        "api_base": api_base,
        "sandbox": sandbox,
        "api_key_env": api_key_env,
        "secrets": str(secrets) if secrets else None,
        "max_steps": max_steps,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "invalid_retries": invalid_retries,
        "max_retries": max_retries,
        "max_http_attempts": max_http_attempts,
        "provider_min_interval_seconds": provider_min_interval_seconds,
        "max_api_calls": max_api_calls,
        "max_tokens_total": max_tokens_total,
        "floor_effect_after": floor_effect_after,
        "reasoning_effort": reasoning_effort,
        "reasoning_enabled": reasoning_effort is not None,
        "request_extra": dict(request_extra or {}),
        "estimated_case_api_calls": case_budget_calls,
        "estimated_case_output_tokens": case_budget_tokens,
        "oracle_preflight": {
            "api_calls": oracle_report.get("api_calls", 0) if oracle_report else None,
            "failure_count": oracle_report.get("failure_count") if oracle_report else None,
            "model_sweep_allowed": oracle_report.get("model_sweep_allowed") if oracle_report else None,
        },
    }
    checkpoint = _load_checkpoint(checkpoint_path, manifest=manifest, metadata=metadata)
    checkpoint["run"].update(metadata)
    checkpoint["paused"] = False
    checkpoint["pause_reason"] = None
    checkpoint["floor_effect"] = bool(checkpoint.get("floor_effect", False))
    checkpoint["floor_effect_streak"] = int(checkpoint.get("floor_effect_streak", 0) or 0)
    result_by_case = _result_by_case(checkpoint)
    cases = list(manifest.get("cases", []))
    if max_cases is not None:
        if max_cases < 1:
            raise ValueError("max-cases must be positive")
        cases = cases[:max_cases]
    estimated_total_tokens = len(cases) * case_budget_tokens
    estimated_total_calls = len(cases) * case_budget_calls
    checkpoint["run"].update(
        {
            "estimated_total_api_calls": estimated_total_calls,
            "estimated_total_output_tokens": estimated_total_tokens,
        }
    )
    if matrix == "all" and not dry_run and max_tokens_total is not None:
        if estimated_total_tokens > max_tokens_total:
            raise ValueError(
                "all-matrix estimate exceeds --max-tokens-total: "
                f"{estimated_total_tokens} > {max_tokens_total}; lower --max-cases or the per-case limits"
            )
    started = time.monotonic()
    api_calls_reserved = sum(
        max_steps * (1 + invalid_retries)
        for row in checkpoint.get("results", [])
        if row.get("status") in {"scored", "infrastructure_error", "paused_provider_error"}
    )
    output_tokens_reserved = api_calls_reserved * max_tokens
    http_attempts_reserved = sum(
        int(row.get("http_attempts", row.get("http_attempt_ceiling", 0)) or 0)
        for row in checkpoint.get("results", [])
        if row.get("status") in {"scored", "infrastructure_error", "paused_provider_error"}
    )
    if max_http_attempts is not None and http_attempts_reserved > max_http_attempts:
        raise ValueError("recorded HTTP attempts exceed the configured bounded budget")
    completed_this_run = 0
    secret = None
    if not dry_run:
        credentials = resolve_provider(
            provider,
            api_key_env=api_key_env,
            api_base=api_base,
            secret_path=secrets,
        )
        secret = credentials.api_key
    for case in cases:
        case_id = str(case.get("case_id", ""))
        if not case_id or not case.get("environment"):
            raise ValueError("every manifest case needs case_id and environment")
        existing = result_by_case.get(case_id)
        if existing and not retry_recorded and existing.get("status") in {
            "scored",
            "generation_error",
            "compile_error",
            "blocked_config_drift",
        }:
            continue
        # A dry-run is a plan, not a completed API case.  It must be possible
        # to resume the same checkpoint in live mode after reviewing its budget.
        if existing and not retry_recorded and dry_run and existing.get("status") == "planned":
            continue
        if max_wall_seconds is not None and time.monotonic() - started >= max_wall_seconds:
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "max_wall_seconds"
            break
        current_hash = _current_config_hash(ROOT, case)
        if current_hash != case.get("config_sha256") and not allow_config_drift:
            result = {
                "case_id": case_id,
                "environment": case.get("environment"),
                "track": case.get("track"),
                "difficulty": case.get("difficulty"),
                "seed": case.get("seed"),
                "status": "blocked_config_drift",
                "error": "config hash differs from the pinned inventory",
            }
            result_by_case[case_id] = result
            checkpoint["results"] = list(result_by_case.values())
            checkpoint["updated_at"] = _utc_now()
            _write_json_atomic(checkpoint_path, checkpoint)
            _write_coverage(output_dir, checkpoint)
            continue
        estimated_calls, estimated_tokens = case_budget_calls, case_budget_tokens
        if max_api_calls is not None and api_calls_reserved + estimated_calls > max_api_calls:
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "max_api_calls"
            break
        if max_tokens_total is not None and output_tokens_reserved + estimated_tokens > max_tokens_total:
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "max_tokens_total"
            break
        if max_output_tokens is not None and output_tokens_reserved + estimated_tokens > max_output_tokens:
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "max_output_tokens"
            break
        case_http_attempt_ceiling: int | None = None
        if max_http_attempts is not None:
            remaining_http_attempts = max_http_attempts - http_attempts_reserved
            if remaining_http_attempts < 1:
                checkpoint["paused"] = True
                checkpoint["pause_reason"] = "max_http_attempts"
                break
            # The ceiling is shared by every logical completion in this
            # subprocess. ProviderClient still caps each logical call at six
            # attempts; this outer ceiling counts all HTTP attempts globally.
            case_http_attempt_ceiling = min(
                remaining_http_attempts,
                estimated_calls * (max_retries + 1),
            )
        if dry_run:
            result = {
                "case_id": case_id,
                "environment": case.get("environment"),
                "track": case.get("track"),
                "difficulty": case.get("difficulty"),
                "seed": case.get("seed"),
                "status": "planned",
                "estimated_api_calls": estimated_calls,
                "estimated_output_tokens": estimated_tokens,
                "http_attempt_ceiling": case_http_attempt_ceiling,
            }
            result_by_case[case_id] = result
            api_calls_reserved += estimated_calls
            output_tokens_reserved += estimated_tokens
            if max_http_attempts is not None:
                http_attempts_reserved += int(case_http_attempt_ceiling or 0)
            completed_this_run += 1
            checkpoint["results"] = list(result_by_case.values())
            checkpoint["updated_at"] = _utc_now()
            _write_json_atomic(checkpoint_path, checkpoint)
            _write_coverage(output_dir, checkpoint)
            continue
        if not secret:
            raise ValueError(f"API key environment variable {api_key_env!r} is not set")
        if min_interval_seconds > 0 and completed_this_run:
            time.sleep(min_interval_seconds)
        case_output = output_dir / "episodes" / _safe_name(case_id)
        command = _build_command(
            case,
            provider=provider,
            model=model,
            api_key_env=api_key_env,
            secrets=secrets,
            api_base=api_base,
            sandbox=sandbox,
            output_dir=case_output,
            max_steps=max_steps,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            invalid_retries=invalid_retries,
            max_http_attempts=case_http_attempt_ceiling,
            provider_min_interval_seconds=provider_min_interval_seconds,
            max_retries=max_retries,
            keep_images=keep_images,
            keep_workspace=keep_workspace,
            reasoning_effort=reasoning_effort,
            request_extra=request_extra,
        )
        case_started = time.monotonic()
        remaining_wall_seconds = None
        if max_wall_seconds is not None:
            remaining_wall_seconds = max(0.1, max_wall_seconds - (case_started - started))
        try:
            process = subprocess.run(
                command,
                cwd=ROOT,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=remaining_wall_seconds,
            )
            stdout = _redact(process.stdout, secret)
            stderr = _redact(process.stderr, secret)
            parsed = _extract_result(process.stdout)
            final = parsed.get("final", {}) if parsed else {}
            reported_http_attempts = (
                parsed.get("http_attempts")
                if isinstance(parsed, dict) and isinstance(parsed.get("http_attempts"), int)
                else None
            )
            if parsed and isinstance(final, dict) and final.get("failure_mode") in {
                "api_error",
                "provider_transient",
            }:
                status = "paused_provider_error"
                error = "provider or quota failure detected; resume only after checking the account"
            elif parsed and isinstance(final, dict) and final.get("failure_mode") == "controller_error":
                status = "infrastructure_error"
                error = "arena controller failed before producing a score"
            elif parsed and isinstance(final, dict) and "verdict" in final:
                status = "scored"
                error = None
            elif _provider_failure(stdout + stderr):
                status = "paused_provider_error"
                error = "provider or quota failure detected; resume only after checking the account"
            else:
                status = "infrastructure_error"
                error = "arena controller did not return a scored result"
            result = {
                "case_id": case_id,
                "environment": case.get("environment"),
                "track": case.get("track"),
                "difficulty": case.get("difficulty"),
                "seed": case.get("seed"),
                "status": status,
                "verdict": final.get("verdict") if isinstance(final, dict) else None,
                "score": final.get("score") if isinstance(final, dict) else None,
                "failure_mode": final.get("failure_mode") if isinstance(final, dict) else None,
                "returncode": process.returncode,
                "elapsed_seconds": round(time.monotonic() - case_started, 3),
                "http_attempts": (
                    reported_http_attempts
                    if reported_http_attempts is not None
                    else case_http_attempt_ceiling
                ),
                "http_attempt_ceiling": case_http_attempt_ceiling,
                "run_dir": parsed.get("run_dir") if parsed else None,
                "reasoning_enabled": reasoning_effort is not None,
                "error": error,
                "stdout_tail": stdout,
                "stderr_tail": stderr,
            }
        except subprocess.TimeoutExpired:
            result = {
                "case_id": case_id,
                "environment": case.get("environment"),
                "track": case.get("track"),
                "difficulty": case.get("difficulty"),
                "seed": case.get("seed"),
                "status": "infrastructure_error",
                "reasoning_enabled": reasoning_effort is not None,
                "http_attempts": case_http_attempt_ceiling,
                "http_attempt_ceiling": case_http_attempt_ceiling,
                "error": "scheduler subprocess timed out",
                "elapsed_seconds": round(time.monotonic() - case_started, 3),
            }
        if not reasoning_effort and _is_zero_score(result):
            checkpoint["floor_effect_streak"] = int(checkpoint.get("floor_effect_streak", 0) or 0) + 1
        else:
            checkpoint["floor_effect_streak"] = 0
        if (
            floor_effect_after is not None
            and checkpoint["floor_effect_streak"] >= floor_effect_after
            and not reasoning_effort
            and _is_zero_score(result)
        ):
            result["floor_effect"] = True
            checkpoint["floor_effect"] = True
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "floor_effect"
        result["floor_effect_streak"] = checkpoint["floor_effect_streak"]
        result_by_case[case_id] = result
        checkpoint["results"] = list(result_by_case.values())
        checkpoint["updated_at"] = _utc_now()
        completed_this_run += 1
        api_calls_reserved += estimated_calls
        output_tokens_reserved += estimated_tokens
        http_attempts_used = int(result.get("http_attempts", 0) or 0)
        if max_http_attempts is not None:
            if http_attempts_used > int(case_http_attempt_ceiling or 0):
                raise ValueError("episode exceeded its bounded HTTP-attempt ceiling")
            http_attempts_reserved += http_attempts_used
        if result.get("status") == "paused_provider_error":
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "provider_error"
        elif result.get("status") == "infrastructure_error":
            # Docker/isolation/controller failures are not model answers. Stop
            # before spending another request on a potentially unsafe runner.
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "infrastructure_error"
        elif max_http_attempts is not None and http_attempts_reserved >= max_http_attempts:
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = "max_http_attempts"
        _write_json_atomic(checkpoint_path, checkpoint)
        _write_coverage(output_dir, checkpoint)
        if checkpoint.get("paused"):
            break
    if dry_run:
        checkpoint["results"] = list(result_by_case.values())
        checkpoint["updated_at"] = _utc_now()
        _write_json_atomic(checkpoint_path, checkpoint)
        _write_coverage(output_dir, checkpoint)
    return checkpoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("runs/suite"))
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="SUITE_API_KEY")
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--sandbox", choices=("docker", "local"), default="docker")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--invalid-retries", type=int, default=2)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-http-attempts", type=int, default=None)
    parser.add_argument("--provider-min-interval-seconds", type=float, default=0.0)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--max-api-calls", type=int, default=None)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument(
        "--max-tokens-total",
        type=int,
        default=None,
        help="required ceiling for live all-matrix execution (estimated output tokens)",
    )
    parser.add_argument("--max-wall-seconds", type=float, default=None)
    parser.add_argument("--min-interval-seconds", type=float, default=0.0)
    parser.add_argument(
        "--floor-effect-after",
        type=int,
        default=3,
        help="pause after this many consecutive non-reasoning scored zeros; use 0 to disable",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high"),
        default=None,
        help="opt into a provider reasoning request; floor-effect detection is disabled",
    )
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-config-drift", action="store_true")
    parser.add_argument("--retry-recorded", action="store_true")
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = _read_json(args.manifest)
        checkpoint = run_suite(
            manifest,
            output_dir=args.out,
            provider=args.provider,
            model=args.model,
            api_key_env=args.api_key_env,
            secrets=args.secrets,
            api_base=args.api_base,
            sandbox=args.sandbox,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            invalid_retries=args.invalid_retries,
            max_retries=args.max_retries,
            max_http_attempts=args.max_http_attempts,
            provider_min_interval_seconds=args.provider_min_interval_seconds,
            max_cases=args.max_cases,
            max_api_calls=args.max_api_calls,
            max_output_tokens=args.max_output_tokens,
            max_tokens_total=args.max_tokens_total,
            max_wall_seconds=args.max_wall_seconds,
            min_interval_seconds=args.min_interval_seconds,
            floor_effect_after=args.floor_effect_after,
            reasoning_effort=args.reasoning_effort,
            checkpoint_path=args.checkpoint,
            dry_run=args.dry_run,
            allow_config_drift=args.allow_config_drift,
            retry_recorded=args.retry_recorded,
            keep_images=args.keep_images,
            keep_workspace=args.keep_workspace,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"suite run failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "out": str(args.out),
                "paused": checkpoint.get("paused", False),
                "pause_reason": checkpoint.get("pause_reason"),
                "floor_effect": checkpoint.get("floor_effect", False),
                "recorded_cases": len(checkpoint.get("results", [])),
                "manifest_cases": checkpoint.get("manifest_case_count"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
