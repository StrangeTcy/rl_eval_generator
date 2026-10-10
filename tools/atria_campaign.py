#!/usr/bin/env python3
"""Run a resilient, provider-pinned covering campaign: every environment, every level.

The historical ``atria_campaign.py`` entry point is retained as a stable CLI,
but profile validation, credentials, API wire surface, reasoning controls,
modality inventory, and scheduler settings are selected from an explicit
provider target in the profile. The campaign evaluates the pinned model across the covering difficulty matrix
built by ``tools/suite_inventory.py`` (every axis level of every registered
environment at seed 0), so a provider outage costs time instead of the run:

1. Provider-free validation first, exactly like the pilot: the modality
   inventory, generation preflight, compile-level oracle preflight, and the
   exact-instance gate over every environment that has a behavioral
   reference.  Environments without a reference run under compile-only
   validation and every one of their result rows is labeled
   ``judge_guarantee=compile_only``.
2. The paid compatibility probe runs only after validation passes; transient
   provider failures are waited out with exponential backoff up to the
   profile's patience window.
3. Episodes run through the checkpointed scheduler with the same in-run
   outage patience. Provider errors, dispatch-wall boundaries, and bounded
   per-case infrastructure retries pause with a resumable checkpoint that the
   supervisor workflow resumes. Budget ceilings and exhausted infrastructure
   retries pause for an operator.

Exit codes: 0 completed (or provider-free gates-only pass); 2 blocked or unexpected error;
3 no credentials; 4 Docker unavailable; 7 compatibility paused; 8 suite paused or incomplete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
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
from arena.providers import Completion, ProviderClient, ProviderError  # noqa: E402
from arena.secrets import redact_text, resolve_provider  # noqa: E402
from tools.atria_first_experiment import (  # noqa: E402
    APPROVED_BASE,
    APPROVED_MODEL,
)
from tools.atria_modality import inventory_selected_modalities  # noqa: E402
from tools.first_experiment import _generation_preflight, _runtime_check  # noqa: E402
from tools.run_suite import (  # noqa: E402
    GateCaseBlockedRepeatedly,
    GateWallExceeded,
    _utc_now,
    run_suite,
)
from tools.suite_inventory import _load_yaml, build_manifest  # noqa: E402

RESUMABLE_PAUSE_REASONS = {
    "provider_error",
    "max_wall_seconds",
    "provider_infrastructure_error_compatibility",
    # The supervisor resumes this only while run_suite's per-case ledger is
    # below its fixed retry bound; it does not resume the exhausted reason.
    "infrastructure_error",
    "docker_unavailable",
    "wrapper_transient_error",
}

CAMPAIGN_TARGETS: dict[str, dict[str, Any]] = {
    "atria": {
        "model": APPROVED_MODEL,
        "api_base": APPROVED_BASE,
        "api_key_env": "ATRIA_API_KEY",
        "input_modalities": ["text"],
    },
    "mercury": {
        "model": "mercury-2.5",
        "api_base": "https://api.inceptionlabs.ai/v1",
        "api_key_env": "INCEPTION_API_KEY",
        "input_modalities": ["text"],
    },
}


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _gate_context_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _manifest_cases_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the selected cases, not incidental manifest timestamps or paths."""
    cases = list(manifest.get("cases") or [])
    return hashlib.sha256(
        json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _campaign_metadata(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return non-secret target identity and optional measurement provenance."""
    target = CAMPAIGN_TARGETS.get(str(profile.get("provider") or ""), {})
    return {
        "name": profile.get("name"),
        "provider": profile.get("provider"),
        "model": profile.get("model"),
        "api_base": profile.get("api_base"),
        "api_key_env": profile.get("api_key_env"),
        "wire_api": profile.get("wire_api", "chat_completions"),
        "reasoning_mode": profile.get("reasoning_mode", "provider_default_uncontrolled"),
        "reasoning_effort": profile.get("reasoning_effort"),
        "declared_input_modalities": list(target.get("input_modalities") or []),
        "research_context": dict(profile.get("research_context") or {})
        if isinstance(profile.get("research_context"), Mapping)
        else None,
    }


def _record_campaign_intent(
    output: Path,
    manifest: Mapping[str, Any],
    *,
    execution_mode: str,
    gate_context_sha: str | None,
    profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the only continuation authority a scheduled run may trust.

    New target profiles bind resumed state to provider, model, endpoint, wire
    surface, effort, and profile identity. The historical Atria campaign keeps
    its original intent shape so artifacts produced by its existing launcher
    remain resumable after this controller is generalized.
    """
    if execution_mode not in {"gates_only", "paid"}:
        raise ValueError(f"invalid campaign execution mode: {execution_mode}")
    selected = dict(profile or {})
    provider = str(selected.get("provider") or "atria")
    name = str(selected.get("name") or "atria_covering_campaign")
    path = output / "campaign_intent.json"
    expected = {
        "schema_version": 1,
        "provider": provider,
        "execution_mode": execution_mode,
        "case_manifest_sha256": _manifest_cases_sha256(manifest),
        "gate_context_sha": gate_context_sha,
    }
    if name != "atria_covering_campaign":
        campaign = _campaign_metadata(selected)
        expected.update(
            {
                "campaign_name": name,
                "model": campaign.get("model"),
                "api_base": campaign.get("api_base"),
                "wire_api": campaign.get("wire_api"),
                "reasoning_effort": campaign.get("reasoning_effort"),
                "campaign_profile_sha256": hashlib.sha256(
                    json.dumps(
                        selected, sort_keys=True, separators=(",", ":"), default=str
                    ).encode("utf-8")
                ).hexdigest(),
            }
        )
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = None
    if isinstance(existing, dict):
        comparable = {key: existing.get(key) for key in expected}
        if comparable != expected:
            raise ValueError(
                "campaign intent differs from the restored state; refuse to "
                "continue with a changed provider, model, mode, manifest, or code context"
            )
        return existing
    value = {**expected, "recorded_at": _utc_now()}
    write_json(path, value)
    return value


def _restored_paid_authorization(output: Path, provider: str = "atria") -> bool:
    """Return whether the staged state itself authorizes a paid resume.

    The authorization is deliberately read only from the persisted intent,
    never from a profile or a present secret.  This keeps a scheduled job
    billable only when its original manual dispatch recorded ``paid`` first.
    """
    try:
        intent = json.loads((output / "campaign_intent.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        try:
            intent = json.loads((output / "campaign_bootstrap.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
    return (
        isinstance(intent, dict)
        and intent.get("provider") == provider
        and intent.get("execution_mode") == "paid"
    )


def _is_explicit_actions_paid_dispatch(profile: Mapping[str, Any] | None = None) -> bool:
    """Recognize explicit manual approval for the historical Atria launcher.

    New launchers pass ``--allow-provider``; the workflow-name compatibility
    path remains restricted to the already-deployed Atria action.
    """
    selected_name = str((profile or {}).get("name") or "atria_covering_campaign")
    expected_workflow = (profile or {}).get("workflow_name")
    if expected_workflow is None and selected_name == "atria_covering_campaign":
        expected_workflow = "Atria covering campaign"
    return (
        selected_name == "atria_covering_campaign"
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_WORKFLOW") == expected_workflow
    )


def _validate_campaign_profile(profile: Mapping[str, Any]) -> None:
    """Fail closed on target identity and the exact API/reasoning contract."""
    # Rehearsal mode: provider custom, no real API calls, exercises checkpoint resume.
    if profile.get("provider") == "custom" and profile.get("name") in {"rehearsal", "rehearsal_autonomous"}:
        if profile.get("api_key_env") not in {"REHEARSAL_API_KEY", "ATRIA_API_KEY", "CUSTOM_API_KEY"}:
            raise ValueError("rehearsal profile must use REHEARSAL_API_KEY or similar")
        return

    provider = str(profile.get("provider") or "")
    target = CAMPAIGN_TARGETS.get(provider)
    if target is None:
        raise ValueError(f"unsupported covering-campaign provider: {provider or '(missing)'}")
    for field in ("model", "api_base", "api_key_env"):
        if profile.get(field) != target[field]:
            raise ValueError(
                f"{provider} campaign profile must pin {field}: {target[field]!r}"
            )

    wire_api = str(profile.get("wire_api", "chat_completions"))
    effort = profile.get("reasoning_effort")
    reasoning_mode = str(profile.get("reasoning_mode", "provider_default_uncontrolled"))
    request_extra = profile.get("request_extra", {})
    if not isinstance(request_extra, Mapping):
        raise ValueError("request_extra must be a mapping")
    if any(key in request_extra for key in ("reasoning", "reasoning_effort")):
        raise ValueError(
            "reasoning controls must use the explicit wire_api/reasoning_effort profile fields"
        )
    if provider == "mercury":
        if wire_api != "chat_completions":
            raise ValueError("Mercury 2.5 campaign requires the Chat Completions wire API")
        if effort != "high" or reasoning_mode != "controlled_chat_reasoning_effort_high":
            raise ValueError(
                "Mercury campaign must request high reasoning through flat Chat Completions reasoning_effort"
            )
    elif wire_api == "responses":
        if effort not in {"low", "medium", "high"}:
            raise ValueError("Atria Responses reasoning requires a named supported effort")
        expected_mode = f"controlled_responses_reasoning_effort_{effort}"
        if reasoning_mode != expected_mode:
            raise ValueError(f"Atria Responses campaign must declare reasoning_mode: {expected_mode}")
        if "temperature" in profile or "top_p" in profile:
            raise ValueError(
                "Atria Responses reasoning profile must not declare Chat Completions sampling controls"
            )
    elif wire_api == "chat_completions":
        if effort is not None:
            raise ValueError(
                "Atria controlled reasoning is Responses-API-only; do not infer a Chat Completions equivalent"
            )
        if reasoning_mode != "provider_default_uncontrolled":
            raise ValueError("Atria Chat Completions profile must declare provider_default_uncontrolled")
    else:
        raise ValueError("wire_api must be 'chat_completions' or 'responses'")

    if profile.get("stream", False) is not False:
        raise ValueError("covering campaigns require stream: false")
    matrix = profile.get("matrix") or {}
    if not isinstance(matrix, Mapping) or matrix.get("mode") != "covering":
        raise ValueError("campaign profile must declare matrix.mode: covering")
    if matrix.get("seeds") != [0]:
        raise ValueError("campaign profile must declare matrix.seeds: [0]")
    resilience = profile.get("resilience") or {}
    if not isinstance(resilience, Mapping):
        raise ValueError("resilience must be a mapping")
    patience = resilience.get("provider_outage_patience_seconds")
    backoff = resilience.get("provider_outage_backoff_seconds")
    if not isinstance(patience, (int, float)) or patience < 0:
        raise ValueError("resilience.provider_outage_patience_seconds must be >= 0")
    if not isinstance(backoff, (int, float)) or backoff <= 0:
        raise ValueError("resilience.provider_outage_backoff_seconds must be > 0")
    if profile.get("unreferenced_compile_only") is not True:
        raise ValueError(
            "campaign profile must set unreferenced_compile_only: true "
            "(compile-only cases are labeled on every result row)"
        )
    job_seconds = profile.get("campaign_job_seconds")
    if not isinstance(job_seconds, int) or job_seconds < 600:
        raise ValueError("campaign_job_seconds must be an integer >= 600")
    limits = profile.get("limits") or {}
    if not isinstance(limits, Mapping):
        raise ValueError("limits must be a mapping")
    for field in (
        "max_steps", "max_tokens", "invalid_retries", "max_retries",
        "max_api_calls", "max_tokens_total", "max_http_attempts",
    ):
        if field not in limits:
            raise ValueError(f"campaign profile limits miss {field}")
    if limits.get("sandbox", "docker") != "docker":
        raise ValueError("covering campaigns require limits.sandbox: docker")
    rate = profile.get("rate_limit") or {}
    if not isinstance(rate, Mapping) or not isinstance(rate.get("min_interval_seconds"), (int, float)) or rate.get("min_interval_seconds", 0) <= 0:
        raise ValueError("rate_limit.min_interval_seconds must be > 0")

    research = profile.get("research_context")
    if profile.get("name") in {"mercury_covering_campaign", "reasoning_atria_covering_campaign"}:
        if not isinstance(research, Mapping):
            raise ValueError("epistemic-process-control campaigns require research_context")
        _validate_research_context(
            research,
            provider=provider,
            model=str(target["model"]),
            api_base=str(target["api_base"]),
            api_key_env=str(target["api_key_env"]),
            wire_api=wire_api,
            effort=effort,
        )
    elif research is not None:
        if not isinstance(research, Mapping):
            raise ValueError("research_context must be a mapping")
        _validate_research_context(
            research,
            provider=provider,
            model=str(target["model"]),
            api_base=str(target["api_base"]),
            api_key_env=str(target["api_key_env"]),
            wire_api=wire_api,
            effort=effort,
        )


def _effective_campaign_job_seconds(profile_seconds: int, requested_seconds: int | None) -> int:
    """Apply a per-invocation wall ceiling without exceeding the pinned profile."""
    maximum = int(profile_seconds)
    if requested_seconds is None:
        return maximum
    if requested_seconds < 600:
        raise ValueError("--job-seconds must be at least 600 seconds")
    if requested_seconds > maximum:
        raise ValueError(
            "--job-seconds may reduce, but must not exceed, profile.campaign_job_seconds"
        )
    return requested_seconds


def _validate_research_context(
    research: Mapping[str, Any],
    *,
    provider: str,
    model: str,
    api_base: str,
    api_key_env: str,
    wire_api: str,
    effort: Any,
) -> None:
    from arena.matched_facts import assert_reporting_boundary

    if research.get("family") != "epistemic_process_control":
        raise ValueError("research_context.family must be epistemic_process_control")
    lineage = research.get("lineage")
    if not isinstance(lineage, Mapping) or (
        lineage.get("from") != "deception"
        or lineage.get("to") != "epistemic_process_control"
        or lineage.get("first_step") != "same_fact_presentation"
    ):
        raise ValueError("research_context.lineage must identify the reframing and T1 first step")
    t1_path = research.get("t1_profile")
    if not isinstance(t1_path, str) or not t1_path:
        raise ValueError("research_context.t1_profile must name a T1 profile")
    profile_path = ROOT / t1_path
    if not profile_path.is_file():
        raise ValueError(f"research_context T1 profile not found: {t1_path}")
    t1_profile = _load_yaml(profile_path)
    t1_target = t1_profile.get("target") or {}
    if not isinstance(t1_target, Mapping):
        raise ValueError("T1 profile target must be a mapping")
    if (
        t1_target.get("provider") != provider
        or t1_target.get("model") != model
        or t1_target.get("api_base") != api_base
        or t1_target.get("api_key_env") != api_key_env
        or t1_target.get("wire_api", "chat_completions") != wire_api
        or t1_target.get("reasoning_effort") != effort
    ):
        raise ValueError("campaign and T1 profile target/API/reasoning identities must match")
    if t1_profile.get("operator") != "same_fact_presentation":
        raise ValueError("research_context T1 profile must use same_fact_presentation")
    endpoints = research.get("endpoint_contract")
    if not isinstance(endpoints, Mapping):
        raise ValueError("research_context.endpoint_contract must be a mapping")
    required = {
        "diagnostic_choices",
        "inquiry_regret",
        "elicited_belief",
        "belief_correctness",
        "calibration_curve",
        "terminal_outcome",
        "recovery",
        "missingness",
        "aggregation",
    }
    missing = sorted(required - set(endpoints))
    if missing:
        raise ValueError(f"endpoint_contract misses separate endpoints/statuses: {missing}")
    expected_endpoints = {
        "diagnostic_choices": "per_arm_menu_choices_and_matched_difference",
        "elicited_belief": "per_arm_posterior_fraction_and_matched_delta",
        "belief_correctness": "per_case_exact_posterior_match_not_calibration",
        "terminal_outcome": "per_arm_answer_and_correctness",
    }
    for endpoint, expected_value in expected_endpoints.items():
        if endpoints.get(endpoint) != expected_value:
            raise ValueError(f"endpoint_contract.{endpoint} must preserve its separate measurement")
    if endpoints.get("inquiry_regret") != "not_measurable_single_turn":
        raise ValueError("single-turn inquiry_regret must be declared not_measurable")
    if endpoints.get("recovery") != "not_measurable_single_turn":
        raise ValueError("single-turn recovery must be declared not_measurable")
    if endpoints.get("calibration_curve") != "unavailable_no_population_metric":
        raise ValueError("do not label correctness as calibration; calibration curve remains unavailable")
    if endpoints.get("missingness") != "not_measurable_or_unavailable_never_zero_filled":
        raise ValueError("missing endpoints must remain not_measurable/unavailable, never zero-filled")
    if endpoints.get("aggregation") != "separate_endpoint_channels_no_composite":
        raise ValueError("T1 endpoint aggregation must keep endpoints separate and avoid composites")
    assert_reporting_boundary(dict(research))


def _optional_credentials(profile: Mapping[str, Any]) -> Any | None:
    """Resolve the pinned provider with explicit env/base but no required key."""
    creds = resolve_provider(
        str(profile["provider"]),
        api_key_env=str(profile["api_key_env"]),
        api_base=str(profile["api_base"]),
        require_key=False,
    )
    return creds if creds.api_key else None


def _compatibility_check(
    profile: Mapping[str, Any], credentials: Any, output: Path
) -> dict[str, Any]:
    """Make one bounded READY probe on the profile's exact wire surface."""
    provider = str(profile["provider"])
    wire_api = str(profile.get("wire_api", "chat_completions"))
    effort = profile.get("reasoning_effort")
    limits = profile["limits"]
    compatibility_max_tokens = int(limits["max_tokens"])
    interval = float(profile["rate_limit"]["min_interval_seconds"])
    max_retries = int(limits["max_retries"])
    extras = dict(profile.get("request_extra") or {})
    if effort is not None and wire_api == "chat_completions":
        extras["reasoning_effort"] = str(effort)
    effective = {
        "provider": provider,
        "api_base": profile["api_base"],
        "model": profile["model"],
        "wire_api": wire_api,
        "max_output_tokens": compatibility_max_tokens,
        "temperature": profile.get("temperature") if wire_api == "chat_completions" else None,
        "top_p": profile.get("top_p") if wire_api == "chat_completions" else None,
        "stream": False,
        "request_extra": extras,
        "reasoning_mode": profile.get("reasoning_mode", "provider_default_uncontrolled"),
        "reasoning_effort": effort,
        "max_retries": max_retries,
        "max_attempts": max_retries + 1,
        "min_interval_seconds": interval,
    }
    client = ProviderClient(
        provider,
        credentials.api_key,
        api_base=str(profile["api_base"]),
        max_retries=max_retries,
        max_http_attempts=max_retries + 1,
        min_interval_seconds=interval,
    )
    messages = [
        {"role": "system", "content": "Return a short compatibility acknowledgement."},
        {"role": "user", "content": "Reply with the single word READY."},
    ]
    try:
        if wire_api == "responses":
            completion: Completion = client.complete_responses(
                messages,
                model=str(profile["model"]),
                reasoning_effort=str(effort) if effort is not None else None,
                max_output_tokens=compatibility_max_tokens,
                request_extra=profile.get("request_extra") or None,
            )
        else:
            # Chat Completions takes ``max_tokens`` only; ProviderClient.complete()
            # has no ``max_output_tokens`` parameter and raises TypeError if one is
            # passed. The Responses-API sibling takes the opposite name.
            completion = client.complete(
                model=str(profile["model"]),
                messages=messages,
                max_tokens=compatibility_max_tokens,
                temperature=float(profile.get("temperature", 0.0)),
                top_p=float(profile["top_p"]) if profile.get("top_p") is not None else None,
                request_extra=extras or None,
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
        write_json(output / "compatibility.json", result, secret=credentials.api_key)
        return result
    expected_finish = "completed" if wire_api == "responses" else "stop"
    valid = (
        completion.status_code is not None
        and 200 <= completion.status_code < 300
        and completion.finish_reason == expected_finish
        and completion.content.strip() == "READY"
        and bool(completion.usage)
    )
    result = {
        "status": "passed" if valid else "failed",
        "effective_request": effective,
        "error_type": None if valid else "invalid_compatibility_completion",
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
        "attempts": max(1, client.http_attempts_used),
        "attempt_logs": client.last_attempt_logs,
        "retry_count": client.last_retry_count,
    }
    write_json(output / "compatibility.json", result, secret=credentials.api_key)
    return result


def _compatibility_with_patience(
    profile: Mapping[str, Any],
    credentials: Any,
    output: Path,
    *,
    patience_seconds: float,
    backoff_seconds: float,
    deadline: float,
) -> tuple[dict[str, Any], float]:
    """Run the paid compatibility probe, waiting out transient provider errors.

    Substantive failures (the probe completes but is not a valid READY
    acknowledgement) return immediately; only provider-transient errors
    consume the patience window.
    """
    waited = 0.0
    retries = 0
    while True:
        compatibility = _compatibility_check(profile, credentials, output / "compatibility.json")
        if compatibility.get("status") == "passed":
            return compatibility, waited
        if compatibility.get("error_type") != "provider_transient":
            return compatibility, waited
        backoff = min(backoff_seconds * (2 ** retries), 600.0)
        remaining_patience = patience_seconds - waited
        remaining_wall = deadline - time.monotonic()
        if patience_seconds <= 0 or backoff >= remaining_patience or backoff >= remaining_wall:
            return compatibility, waited
        waited += backoff
        retries += 1
        _sleep(backoff)


def _report_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    compatibility: Mapping[str, Any] | None,
    compat_waited: float,
    status: str,
    pause_reason: str | None,
) -> dict[str, Any]:
    results = list(checkpoint.get("results", []))
    by_guarantee: dict[str, dict[str, int]] = {}
    for row in results:
        guarantee = str(row.get("judge_guarantee", "behavioral_reference"))
        bucket = by_guarantee.setdefault(guarantee, {})
        status_key = str(row.get("status", "unknown"))
        bucket[status_key] = bucket.get(status_key, 0) + 1
        if status_key == "scored":
            verdict_key = str(row.get("verdict") or "unknown").lower()
            bucket[f"verdict_{verdict_key}"] = bucket.get(f"verdict_{verdict_key}", 0) + 1
    gate = checkpoint.get("instance_gate") or {}
    report: dict[str, Any] = {
        "schema_version": 1,
        "event": "covering_campaign",
        "status": status,
        "pause_reason": pause_reason,
        "resumable": pause_reason in RESUMABLE_PAUSE_REASONS if pause_reason else False,
        "recorded_cases": len(results),
        "results_by_judge_guarantee": by_guarantee,
        "gated_case_count": gate.get("gated_case_count"),
        "compile_only_case_count": gate.get("compile_only_case_count"),
        "gate_carried": bool(isinstance(gate.get("report"), dict) and gate["report"].get("carried_from_checkpoint")),
        "provider_outage": checkpoint.get("provider_outage"),
        "compatibility": {
            "status": compatibility.get("status") if compatibility else None,
            "attempts": compatibility.get("attempts") if compatibility else None,
            "waited_seconds": round(compat_waited, 1),
        },
        # Two separate denominators by design: never report a combined
        # pass rate across judge guarantees. gated_case_count and
        # compile_only_case_count above are those denominators.
        "aggregate_note": (
            "report per judge_guarantee bucket only; compile_only verdicts "
            "are exploratory and excluded from any validated aggregate"
        ),
        "compile_only_disclaimer": (
            "compile_only rows are graded by judges without a behavioral "
            "reference on that exact instance; they do not carry the "
            "exact-instance oracle guarantee and must not be read as "
            "validated model verdicts"
        ),
    }
    return report


def _load_report_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _campaign_failure_diagnostics(output: Path) -> dict[str, Any]:
    """Extract concise, redacted provider-free failures for reports and logs."""
    generation = _load_report_file(output / "generation_preflight.json")
    generation_rows = generation.get("cases") or []
    generation_failures = [
        {
            "case_id": row.get("case_id"),
            "status": row.get("status"),
            "error": redact_text(str(row.get("error") or ""))[:1600],
        }
        for row in generation_rows
        if isinstance(row, dict) and row.get("status") != "ready"
    ]

    oracle = _load_report_file(output / "instance_oracles.json")
    oracle_rows = oracle.get("cases") or []
    failed_cases: list[dict[str, Any]] = []
    for row in oracle_rows:
        if not isinstance(row, dict) or row.get("status") == "passed":
            continue
        failed_variants = []
        for variant in row.get("variants") or []:
            if not isinstance(variant, dict) or variant.get("accepted") is True:
                continue
            failed_variants.append({
                "variant": variant.get("variant"),
                "verdict": variant.get("verdict"),
                "failure_mode": variant.get("failure_mode"),
                "checks": variant.get("checks") or {},
                "stderr_tail": redact_text(str(variant.get("stderr_tail") or ""))[-600:],
            })
        failed_cases.append({
            "case_id": row.get("case_id"),
            "environment": row.get("environment"),
            "status": row.get("status"),
            "reason": redact_text(str(row.get("reason") or ""))[:800],
            "failed_variants": failed_variants,
        })

    partial = _load_report_file(output / "instance_oracles_partial.json")
    partial_failures = []
    rows = partial.get("rows")
    if isinstance(rows, dict):
        for case_id, entry in rows.items():
            if not isinstance(entry, dict):
                continue
            row = entry.get("row")
            if isinstance(row, dict) and row.get("status") != "passed":
                partial_failures.append({
                    "case_id": case_id,
                    "status": row.get("status"),
                    "reason": redact_text(str(row.get("reason") or ""))[:800],
                    "attempts": entry.get("attempts"),
                })

    return {
        "generation_preflight_failed_cases": generation_failures,
        "exact_instance_failed_cases": failed_cases,
        "partial_exact_instance_failed_cases": partial_failures,
    }


def _format_failure_diagnostics(diagnostics: Mapping[str, Any]) -> str:
    details: list[str] = []
    for key, label in (
        ("generation_preflight_failed_cases", "generation"),
        ("exact_instance_failed_cases", "exact-instance oracle"),
        ("partial_exact_instance_failed_cases", "partial exact-instance oracle"),
    ):
        failures = diagnostics.get(key) or []
        for row in failures[:20]:
            case_id = row.get("case_id") or "unknown case"
            reason = row.get("error") or row.get("reason") or row.get("status")
            details.append(f"{label}: {case_id} ({reason or 'failed'})")
    if not details:
        return ""
    suffix = " Provider-free diagnostics: " + "; ".join(details)
    return suffix[:6000]


def _recorded_episode_count(output: Path) -> int:
    """How many episodes the restored checkpoint has already banked."""
    try:
        checkpoint = json.loads(
            (output / "suite_checkpoint.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return 0
    results = checkpoint.get("results")
    return len(results) if isinstance(results, list) else 0


def _should_reset_output(
    output: Path,
    *,
    explicit_fresh: bool,
    profile: Mapping[str, Any],
    environ: Mapping[str, str],
) -> tuple[bool, str]:
    """Decide whether to delete the campaign output directory.

    History: this decision used to be inline and inferred a fresh start from
    ``GITHUB_EVENT_NAME == "workflow_dispatch"`` alone, on the assumption that
    "resumes arrive as schedule events". When the workflow gained a
    self-dispatched continuation, resumes started arriving as
    workflow_dispatch, and the restored state artifact was deleted immediately
    after being restored -- destroying 73 banked episodes and ~12h of gate
    rows over several legs before anyone noticed.

    The lesson is not "fix the event name" (that is done in the workflow); it
    is that an *inferred* fresh start must never be destructive. Deleting
    recorded work now requires explicit operator intent via --fresh. Any
    future wiring mistake costs a redundant no-op, not the campaign.
    """
    if explicit_fresh:
        return True, "explicit --fresh"
    if (
        profile.get("provider") != "atria"
        or profile.get("name") not in {None, "atria_covering_campaign"}
    ):
        return False, "non-legacy campaign output is preserved unless --fresh is explicit"
    if environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        return False, f"event {environ.get('GITHUB_EVENT_NAME') or 'local'} is a resume"
    recorded = _recorded_episode_count(output)
    if recorded > 0:
        return False, (
            f"refusing to infer a fresh start: {recorded} recorded episodes "
            f"would be destroyed; pass --fresh to discard them deliberately"
        )
    return True, "workflow_dispatch with no recorded episodes"


def _reset_fresh_campaign_output(output: Path) -> None:
    """Remove stale checked-in rehearsal artifacts on an explicit fresh run.

    Manual workflow_dispatch runs are fresh, not resumes. The workflow writes
    campaign_ref.txt immediately before invoking this script; preserve that
    pin while discarding old reports/checkpoints that would otherwise poison
    the new manifest (the repository contains five-case rehearsal artifacts).
    """
    resolved = output.resolve()
    repo_root = ROOT.resolve()
    git_dir = repo_root / ".git"
    if resolved == repo_root or resolved in repo_root.parents:
        raise ValueError(f"refusing to reset unsafe campaign output path: {output}")
    if resolved == git_dir or git_dir in resolved.parents:
        raise ValueError(f"refusing to reset Git metadata path: {output}")
    if output.is_symlink():
        raise ValueError(f"refusing to reset a symlink campaign output: {output}")

    pinned_ref = ""
    ref_path = output / "campaign_ref.txt"
    if ref_path.is_file() and not ref_path.is_symlink():
        try:
            pinned_ref = ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            pinned_ref = ""

    if output.exists():
        known_state_files = {
            "campaign_ref.txt", "suite_checkpoint.json", "instance_oracles_partial.json",
            "campaign_report.json", "pilot_manifest.json", "generation_preflight.json",
            "t1_started.json", "t1_same_fact_presentation.json",
        }
        if not output.is_dir() or not any((output / name).exists() for name in known_state_files):
            raise ValueError(
                f"refusing to clear {output}: it does not contain recognizable campaign state"
            )
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    if pinned_ref:
        (output / "campaign_ref.txt").write_text(pinned_ref + "\n", encoding="utf-8")


def _mark_terminal(output: Path, reason: str, detail: str) -> None:
    """Record a non-resumable end so the supervisor stops instead of
    restarting a deterministically failing wrapper forever.  The marker is
    cleared at the start of every run: one automatic restart is allowed and a
    human decision after that."""
    diagnostics = _campaign_failure_diagnostics(output)
    detail = redact_text(detail) + _format_failure_diagnostics(diagnostics)
    try:
        write_json(output / "wrapper_failed.json", {
            "pause_reason": reason,
            "detail": detail,
            "diagnostics": diagnostics,
            "recorded_at": _utc_now(),
        })
    except OSError:
        pass


def _order_cases_referenced_first(manifest: dict) -> None:
    """Sort cases so environments with an exact-instance oracle reference run
    before compile-only ones, preserving the deterministic order inside each
    group.  Rationale: budget and floor-effect pauses are non-resumable, so
    if the campaign is cut short, the cut must land on compile-only cases —
    whose verdicts are already labeled unvalidated — never on validated
    ones."""
    from tools.instance_oracle_gate import REFERENCES  # lazy: needs torch

    referenced_envs = set(REFERENCES)
    manifest["cases"] = sorted(
        manifest["cases"],
        key=lambda case: str(case.get("environment")) not in referenced_envs,
    )
    manifest["campaign_case_ordering"] = {
        "policy": "referenced_environments_first",
        "reason": "non-resumable pauses must cut compile-only cases, not validated ones",
        "referenced_case_count": sum(
            1 for case in manifest["cases"]
            if str(case.get("environment")) in referenced_envs
        ),
    }


def _apply_gate_blocked_exclusions(manifest: dict, profile: Mapping[str, Any]) -> None:
    """Omit explicitly reviewed, exact gate-blocked cases before any provider use.

    This is deliberately separate from modality omissions: these cases are
    text-compatible, but the recorded gate run found calibration-apparatus
    defects. Unknown or duplicate IDs fail closed so profile drift cannot
    silently broaden or weaken the campaign.
    """
    configured = profile.get("manual_gate_blocked_exclusions") or {}
    entries = configured.get("cases") or []
    if not entries:
        return
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ValueError("manual_gate_blocked_exclusions.cases must be a list of mappings")
    excluded_ids = [str(item.get("case_id") or "") for item in entries]
    if any(not case_id for case_id in excluded_ids):
        raise ValueError("every manual gate-blocked exclusion requires case_id")
    if len(excluded_ids) != len(set(excluded_ids)):
        raise ValueError("manual gate-blocked exclusion case_ids must be unique")

    original_cases = list(manifest.get("cases") or [])
    by_id = {str(case.get("case_id")): case for case in original_cases}
    unknown = sorted(set(excluded_ids) - set(by_id))
    if unknown:
        raise ValueError(f"manual gate-blocked exclusions are absent from manifest: {unknown}")
    omitted = [by_id[case_id] for case_id in excluded_ids]
    excluded = set(excluded_ids)
    manifest["cases"] = [
        case for case in original_cases if str(case.get("case_id")) not in excluded
    ]
    manifest["case_count"] = len(manifest["cases"])

    # Re-check covering-level accounting after the omissions. Every level in
    # the original covering manifest must remain served or be named by an
    # exact reviewed omission; an unexplained coverage hole fails closed.
    required = {
        (str(case.get("environment")), str(axis), str(level))
        for case in original_cases
        for axis, level in (case.get("difficulty_levels") or {}).items()
    }
    served = {
        (str(case.get("environment")), str(axis), str(level))
        for case in manifest["cases"]
        for axis, level in (case.get("difficulty_levels") or {}).items()
    }
    explicitly_omitted = {
        (str(case.get("environment")), str(axis), str(level))
        for case in omitted
        for axis, level in (case.get("difficulty_levels") or {}).items()
    }
    unexplained = sorted(required - served - explicitly_omitted)
    if unexplained:
        raise ValueError(f"unexplained covering-level gaps after exclusions: {unexplained}")
    omitted_levels = sorted(required - served)

    manifest["known_gate_blocked_omissions"] = {
        "omitted_case_ids": excluded_ids,
        "omitted_case_count": len(excluded_ids),
        "reason": configured.get("reason", "known_gate_blocked_calibration_failures"),
        "disposition": "omitted_before_provider_access",
        "provider_calls_before_omission": 0,
        "provenance": dict(configured.get("provenance") or {}),
        "cases": [dict(item) for item in entries],
        "level_coverage_check": {
            "status": "passed_with_explicit_omissions",
            "unexplained_missing_levels": [],
            "explicitly_omitted_levels": [
                {"environment": env, "axis": axis, "level": level}
                for env, axis, level in omitted_levels
            ],
        },
        "statement": (
            "known judge/reference calibration failures; omitted before provider "
            "access and excluded from scored results"
        ),
    }


def _add_omissions_to_report(report: dict[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("campaign_omissions"):
        report["campaign_omissions"] = manifest["campaign_omissions"]
    if manifest.get("known_gate_blocked_omissions"):
        report["known_gate_blocked_omissions"] = manifest["known_gate_blocked_omissions"]
    campaign = manifest.get("campaign")
    if isinstance(campaign, Mapping):
        report["campaign"] = dict(campaign)
        if campaign.get("name"):
            report["event"] = campaign["name"]
        for field in ("provider", "model", "wire_api", "reasoning_mode", "reasoning_effort"):
            if campaign.get(field) is not None:
                report[field] = campaign[field]
    return report


def _rehearsal_fake_episode_runner():
    """Fake episode runner for rehearsal: no Docker, no provider, exercises wall interruption and transient errors."""
    attempt_counter: dict[str, int] = {}

    def _episode(final, http_attempts=1, returncode=0):
        return subprocess.CompletedProcess(
            [],
            returncode,
            stdout=json.dumps({"run_dir": "runs/fake", "http_attempts": http_attempts, "final": final}),
            stderr="",
        )

    def _provider_error_episode(http_attempts=2):
        return _episode(
            {"verdict": "FAIL", "score": 0.0, "failure_mode": "api_error"},
            http_attempts=http_attempts,
            returncode=1,
        )

    def _scored_episode(http_attempts=1, verdict="PASS", score=1.0):
        return _episode(
            {"verdict": verdict, "score": score, "failure_mode": "pass" if verdict == "PASS" else "fail"},
            http_attempts=http_attempts,
            returncode=0,
        )

    def fake_run(command, **kwargs):
        cmd_str = " ".join(str(p) for p in command)
        if "arena.py" in cmd_str and "run" in cmd_str:
            try:
                env_idx = command.index("--env")
                env_name = command[env_idx + 1]
            except (ValueError, IndexError):
                env_name = "unknown"
            time.sleep(2.0)  # simulate work to consume wall budget
            key = env_name
            count = attempt_counter.get(key, 0)
            attempt_counter[key] = count + 1
            if env_name == "epistemic_games" and count == 0:
                return _provider_error_episode(http_attempts=2)
            if env_name == "epistemic_games":
                return _scored_episode(http_attempts=1, verdict="FAIL", score=0.0)
            return _scored_episode(http_attempts=1, verdict="PASS", score=1.0)
        return subprocess.run(command, **kwargs)

    return fake_run


def _run_rehearsal_mode(profile: Mapping[str, Any], output: Path, args, started: float) -> int:
    """Rehearsal: 5-case manifest, fake episodes, wall interruption, transient provider errors, no real provider calls."""
    import unittest.mock as mock

    # Build manifest: if profile has explicit cases, use them, else use atria_first5 5 cases
    if profile.get("cases"):
        # Build from inventory but select only profile cases
        from tools.first_experiment import EXPECTED_CASES as FIRST5
        manifest_all = build_manifest(root=ROOT, matrix="all", seeds=[0], dry_run=False)
        selected = []
        for env, diff in FIRST5:
            m = [c for c in manifest_all["cases"] if c["environment"] == env and c["difficulty"] == diff and c["seed"] == 0]
            if len(m) != 1:
                raise ValueError(f"inventory missing {env} {diff}")
            selected.append(m[0])
        env_by_name = {item["environment"]: item for item in manifest_all.get("environments", [])}
        selected_envs = [env_by_name[env] for env, _ in FIRST5]
        manifest = dict(manifest_all)
        manifest.update(
            {
                "case_count": len(selected),
                "environment_count": len(selected_envs),
                "cases": selected,
                "environments": selected_envs,
            }
        )
    else:
        # Use covering but for rehearsal we still limit to 5 cases for speed
        manifest_all = build_manifest(root=ROOT, matrix="all", seeds=[0], dry_run=False)
        from tools.first_experiment import EXPECTED_CASES as FIRST5
        selected = []
        for env, diff in FIRST5:
            m = [c for c in manifest_all["cases"] if c["environment"] == env and c["difficulty"] == diff and c["seed"] == 0]
            selected.append(m[0])
        env_by_name = {item["environment"]: item for item in manifest_all.get("environments", [])}
        selected_envs = [env_by_name[env] for env, _ in FIRST5]
        manifest = dict(manifest_all)
        manifest.update(
            {
                "case_count": len(selected),
                "environment_count": len(selected_envs),
                "cases": selected,
                "environments": selected_envs,
            }
        )

    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "pilot_manifest.json", manifest)
    # Minimal modality and generation preflight (fast)
    try:
        modality = inventory_selected_modalities(manifest, root=ROOT)
    except Exception as exc:
        modality = {"error": str(exc), "all_selected_cases_text_only_compatible": True, "unsupported_case_ids": []}
    write_json(output / "modality_inventory.json", modality)
    from tools.first_experiment import _generation_preflight

    generation = _generation_preflight(manifest)
    write_json(output / "generation_preflight.json", {"cases": generation})

    # Fake oracle and instance reports for speed
    fake_oracle = {
        "schema_version": 1,
        "api_calls": 0,
        "failure_count": 0,
        "model_sweep_allowed": True,
        "behavioral_coverage_complete": True,
        "instance_coverage_complete": True,
    }
    fake_instance = {
        "schema_version": 1,
        "provider_calls": 0,
        "instance_coverage_complete": True,
        "cases": [
            {"case_id": c["case_id"], "environment": c["environment"], "status": "passed", "provider_calls": 0, "variants": []}
            for c in manifest["cases"]
        ],
    }
    write_json(output / "oracle_preflight.json", fake_oracle)
    write_json(output / "instance_oracles.json", fake_instance)

    # Determine wall budget based on existing checkpoint
    checkpoint_path = output / "suite_checkpoint.json"
    existing = None
    if checkpoint_path.is_file():
        try:
            existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            existing = None
    if existing and existing.get("results"):
        wall_seconds = 300.0
    else:
        wall_seconds = 7.0

    limits = profile.get("limits", {})
    # Use profile limits but override wall for rehearsal
    job_seconds = int(profile.get("campaign_job_seconds", 60))
    resilience = profile.get("resilience", {})
    patience = float(resilience.get("provider_outage_patience_seconds", 60))
    backoff = float(resilience.get("provider_outage_backoff_seconds", 1))

    # Mock provider resolution
    def fake_resolve(provider, api_key_env=None, api_base=None, secret_path=None, environ=None, require_key=True):
        from arena.secrets import ProviderCreds

        return ProviderCreds(
            name=provider,
            api_key="fake-rehearsal-key",
            api_base=api_base or "https://example.invalid/v1",
            enabled=True,
            default_model=None,
            extra={},
            source="env:REHEARSAL_API_KEY",
        )

    fake_runner = _rehearsal_fake_episode_runner()

    import tools.run_suite as rs

    with mock.patch("tools.run_suite.resolve_provider", side_effect=fake_resolve):
        with mock.patch("tools.run_suite.subprocess.run", side_effect=fake_runner):
            with mock.patch("tools.run_suite._sleep", side_effect=lambda s: time.sleep(0.1)):
                with mock.patch("tools.oracle_preflight.validate_manifest_oracles", return_value=fake_oracle):
                    with mock.patch("tools.instance_oracle_gate.validate_manifest_instances", return_value=fake_instance):
                        checkpoint = run_suite(
                            manifest,
                            output_dir=output,
                            provider="custom",
                            model="offline/pinned",
                            api_key_env="REHEARSAL_API_KEY",
                            api_base="https://example.invalid/v1",
                            sandbox="docker",
                            max_steps=int(limits.get("max_steps", 1)),
                            max_tokens=int(limits.get("max_tokens", 7)),
                            temperature=float(profile.get("temperature", 0.0)),
                            top_p=float(profile.get("top_p", 0.0)) if profile.get("top_p") else None,
                            invalid_retries=int(limits.get("invalid_retries", 0)),
                            max_retries=int(limits.get("max_retries", 1)),
                            max_http_attempts=int(limits.get("max_http_attempts", 100)),
                            provider_min_interval_seconds=float(profile.get("rate_limit", {}).get("min_interval_seconds", 0.1)),
                            max_api_calls=int(limits.get("max_api_calls", 100)),
                            max_tokens_total=int(limits.get("max_tokens_total", 66000000)) if limits.get("max_tokens_total") else None,
                            max_wall_seconds=wall_seconds,
                            min_interval_seconds=float(profile.get("rate_limit", {}).get("min_interval_seconds", 0.1)),
                            floor_effect_after=int(limits.get("floor_effect_after", 0)),
                            request_extra={},
                            checkpoint_path=checkpoint_path,
                            allow_compile_only_oracles=True,
                            unreferenced_compile_only=False,
                            provider_outage_patience_seconds=patience,
                            provider_outage_backoff_seconds=backoff,
                            gate_context_sha="rehearsal-context-sha",
                        )

    if checkpoint.get("paused") and checkpoint.get("pause_reason") in {"max_wall_seconds", "provider_error"}:
        # Set old updated_at to bypass 1200s supervisor backoff for fast rehearsal
        checkpoint["updated_at"] = "2026-09-20T00:00:00+00:00"
        write_json(checkpoint_path, checkpoint)

    status = "paused" if checkpoint.get("paused") else "completed"
    report = {
        "schema_version": 1,
        "event": "rehearsal_campaign",
        "status": status,
        "pause_reason": checkpoint.get("pause_reason"),
        "resumable": checkpoint.get("pause_reason") in RESUMABLE_PAUSE_REASONS if checkpoint.get("pause_reason") else False,
        "recorded_cases": len(checkpoint.get("results", [])),
        "manifest_case_count": manifest["case_count"],
        "results": checkpoint.get("results", []),
        "provider_outage": checkpoint.get("provider_outage"),
        "http_attempts_total": checkpoint.get("http_attempts_total"),
        "updated_at": checkpoint.get("updated_at"),
        "wall_seconds_used": wall_seconds,
        "rehearsal_note": "simulated provider, no real API calls, exercises checkpoint resume and transient error handling",
        "pinned_manifest": {
            "cases": [{"environment": c["environment"], "difficulty": c["difficulty"], "seed": c["seed"]} for c in manifest["cases"]],
            "commit": manifest.get("repository", {}).get("commit"),
        },
    }
    write_json(output / "campaign_report.json", report)
    print(f"Rehearsal {status}; inspect {output}")
    return 0 if status == "completed" else 8


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "experiments" / "atria_campaign.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "atria_campaign")
    parser.add_argument(
        "--job-seconds",
        type=int,
        help="lower this invocation's wall ceiling; cannot exceed the profile maximum",
    )
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument(
        "--fresh", action="store_true",
        help="clear recognizable prior campaign state before starting a fresh campaign",
    )
    parser.add_argument(
        "--gates-only", action="store_true",
        help="stop after provider-free gates; do not check credentials or call the provider",
    )
    parser.add_argument(
        "--allow-provider", action="store_true",
        help=(
            "explicitly authorize the paid phase after the provider-free gates; "
            "without this flag the controller exits before credentials, Docker, "
            "compatibility probes, or provider requests"
        ),
    )
    args = parser.parse_args(argv)
    if args.gates_only and args.allow_provider:
        parser.error("--gates-only and --allow-provider are mutually exclusive")
    output = args.out
    profile: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    try:
        started = time.monotonic()
        profile = _load_yaml(args.profile)
        _validate_campaign_profile(profile)

        reset, reset_reason = _should_reset_output(
            output, explicit_fresh=bool(args.fresh), profile=profile, environ=os.environ
        )
        print(f"campaign output reset={reset} ({reset_reason})")
        if reset:
            _reset_fresh_campaign_output(output)
        else:
            output.mkdir(parents=True, exist_ok=True)

        # A terminal-failure marker from a previous dispatch is cleared at
        # the start of every run: one automatic restart is allowed, a repeat
        # failure rewrites it and the supervisor stands down for an operator.
        marker = output / "wrapper_failed.json"
        marker.unlink(missing_ok=True)

        # Rehearsal mode: custom provider, no real API calls
        if profile.get("provider") == "custom" and profile.get("name") in {"rehearsal", "rehearsal_autonomous"}:
            return _run_rehearsal_mode(profile, output, args, started)

        limits = profile["limits"]
        resilience = profile["resilience"]
        job_seconds = _effective_campaign_job_seconds(
            int(profile["campaign_job_seconds"]), args.job_seconds
        )
        patience = float(resilience["provider_outage_patience_seconds"])
        backoff = float(resilience["provider_outage_backoff_seconds"])

        manifest = build_manifest(root=ROOT, matrix="covering", seeds=[0])
        _apply_gate_blocked_exclusions(manifest, profile)
        target = CAMPAIGN_TARGETS[str(profile["provider"])]
        manifest["campaign"] = _campaign_metadata(profile)
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "pilot_manifest.json", manifest)
        modality = inventory_selected_modalities(
            manifest,
            root=ROOT,
            provider=str(profile["provider"]),
            model=str(profile["model"]),
            input_modalities=list(target["input_modalities"]),
        )
        unsupported = list(modality.get("unsupported_case_ids") or [])
        if unsupported and len(unsupported) < len(manifest.get("cases", [])):
            # The provider cannot serve some environments (e.g. non-text
            # input).  Omit them loudly instead of blocking the campaign:
            # every omission is recorded in the manifest, the inventory, and
            # the final report, and the omitted environments are listed for
            # the operator to run on a provider that supports their modality.
            supported = [
                case for case in manifest["cases"]
                if str(case.get("case_id")) not in set(unsupported)
            ]
            omitted_environments = sorted({
                str(case.get("environment")) for case in manifest["cases"]
                if str(case.get("case_id")) in set(unsupported)
            })
            manifest["cases"] = supported
            manifest["case_count"] = len(supported)
            manifest["campaign_omissions"] = {
                "omitted_case_ids": unsupported,
                "omitted_environments": omitted_environments,
                "reason": "provider_input_modality_unsupported",
                "provider": str(profile["provider"]),
                "provider_input_modalities": list(target["input_modalities"]),
            }
            write_json(output / "pilot_manifest.json", manifest)
            modality = inventory_selected_modalities(
                manifest,
                root=ROOT,
                provider=str(profile["provider"]),
                model=str(profile["model"]),
                input_modalities=list(target["input_modalities"]),
            )
        # Budget exhaustion and floor effects pause non-resuably, so the
        # validated cases must complete before the compile-only ones.
        _order_cases_referenced_first(manifest)
        write_json(output / "pilot_manifest.json", manifest)
        write_json(output / "modality_inventory.json", modality)
        modality_compatible = modality.get(
            "all_selected_cases_provider_modality_compatible",
            modality.get("all_selected_cases_text_only_compatible", False),
        )
        if not modality_compatible:
            pause_reason = f"unsupported_non_text_input_for_{profile['provider']}"
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "blocked", "pause_reason": pause_reason,
                "resumable": False,
            }, manifest))
            _mark_terminal(output, pause_reason,
                           f"provider {profile['provider']} cannot serve the selected modalities")
            print(f"Campaign blocked by modality inventory; inspect {output}")
            return 2
        generation = _generation_preflight(manifest)
        write_json(output / "generation_preflight.json", {"cases": generation})
        if any(item.get("status") != "ready" for item in generation):
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "blocked", "pause_reason": "generation_preflight_failed",
                "resumable": False,
            }, manifest))
            _mark_terminal(output, "generation_preflight_failed",
                           "generation preflight produced non-ready cases")
            print(f"Campaign blocked by generation preflight; inspect {output}")
            return 2

        cases = list(manifest.get("cases", []))
        theoretical = int(limits["max_retries"]) + 1 + (
            len(cases)
            * int(limits["max_steps"])
            * (1 + int(limits["invalid_retries"]))
            * (int(limits["max_retries"]) + 1)
        )
        if theoretical > int(limits["max_http_attempts"]):
            raise ValueError(
                "campaign theoretical HTTP-attempt bound exceeds the configured ceiling: "
                f"{theoretical} > {limits['max_http_attempts']}"
            )

        gate_context_sha = _gate_context_sha()
        # New launchers pass --allow-provider.  The already-deployed launcher
        # is also safe to use: its named manual workflow_dispatch is the one
        # explicit paid approval, and every later scheduled job must inherit
        # that authorization from the staged campaign_intent.json.
        provider_access_allowed = (
            not args.gates_only
            and (
                args.allow_provider
                or _is_explicit_actions_paid_dispatch(profile)
                or _restored_paid_authorization(output, str(profile["provider"]))
            )
        )
        execution_mode = "paid" if provider_access_allowed else "gates_only"
        _record_campaign_intent(
            output,
            manifest,
            execution_mode=execution_mode,
            gate_context_sha=gate_context_sha,
            profile=profile,
        )
        scheduler_kwargs: dict[str, Any] = {
            "output_dir": output,
            "provider": str(profile["provider"]),
            "model": str(profile["model"]),
            "api_key_env": str(profile["api_key_env"]),
            "api_base": str(profile["api_base"]),
            "sandbox": str(limits.get("sandbox", "docker")),
            "max_steps": int(limits["max_steps"]),
            "max_tokens": int(limits["max_tokens"]),
            "temperature": float(profile.get("temperature", 0.0)),
            "top_p": float(profile["top_p"]) if profile.get("top_p") is not None else None,
            "invalid_retries": int(limits["invalid_retries"]),
            "max_retries": int(limits["max_retries"]),
            "max_http_attempts": int(limits["max_http_attempts"]),
            "provider_min_interval_seconds": float(profile["rate_limit"]["min_interval_seconds"]),
            "max_api_calls": int(limits["max_api_calls"]),
            "max_tokens_total": int(limits["max_tokens_total"]),
            "min_interval_seconds": float(profile["rate_limit"]["min_interval_seconds"]),
            "floor_effect_after": int(limits.get("floor_effect_after", 0)),
            "wire_api": str(profile.get("wire_api", "chat_completions")),
            "reasoning_effort": (
                str(profile["reasoning_effort"])
                if profile.get("reasoning_effort") is not None
                else None
            ),
            "request_extra": dict(profile.get("request_extra") or {}),
            "checkpoint_path": output / "suite_checkpoint.json",
            "allow_compile_only_oracles": True,
            "unreferenced_compile_only": True,
            "provider_outage_patience_seconds": patience,
            "provider_outage_backoff_seconds": backoff,
            "gate_context_sha": gate_context_sha,
            "keep_images": args.keep_images,
            "keep_workspace": args.keep_workspace,
        }

        # Phase 1: provider-free validation only.  Writes the checkpoint with
        # the carry-able gate record and touches no provider.  The gate can
        # cost more CPU-hours than one job, so it is bounded by the same job
        # clock with an explicit upload reserve: when the budget runs out
        # mid-gate the banked rows pause resumably instead of being killed by
        # the runner's job-level cancellation before the state upload.
        gate_wall_seconds = max(
            60.0, job_seconds - 900.0 - (time.monotonic() - started)
        )
        try:
            checkpoint = run_suite(
                manifest, stop_after_gates=True,
                gate_wall_seconds=gate_wall_seconds, **scheduler_kwargs,
            )
        except GateCaseBlockedRepeatedly as exc:
            diagnostics = _campaign_failure_diagnostics(output)
            detail = redact_text(str(exc)) + _format_failure_diagnostics(diagnostics)
            write_json(marker, {
                "pause_reason": "gate_case_repeatedly_blocked",
                "detail": detail,
                "diagnostics": diagnostics,
                "recorded_at": _utc_now(),
            })
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "blocked",
                "pause_reason": "gate_case_repeatedly_blocked",
                "resumable": False,
                "detail": detail,
                "diagnostics": diagnostics,
                "compile_only_disclaimer": (
                    "compile_only rows are graded by judges without a "
                    "behavioral reference on that exact instance; they do "
                    "not carry the exact-instance oracle guarantee and must "
                    "not be read as validated model verdicts"
                ),
            }, manifest))
            print(f"Campaign blocked: {detail}; inspect {output}")
            return 2
        except GateWallExceeded as exc:
            partial_path = output / "instance_oracles_partial.json"
            banked = 0
            try:
                banked = len(json.loads(
                    partial_path.read_text(encoding="utf-8")
                ).get("rows") or {})
            except (OSError, json.JSONDecodeError):
                banked = 0
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "paused",
                "pause_reason": "max_wall_seconds",
                "resumable": True,
                "note": "gate_in_progress",
                "gate_rows_banked": banked,
                "detail": redact_text(str(exc)),
                "compile_only_disclaimer": (
                    "compile_only rows are graded by judges without a "
                    "behavioral reference on that exact instance; they do "
                    "not carry the exact-instance oracle guarantee and must "
                    "not be read as validated model verdicts"
                ),
            }, manifest))
            print(f"Campaign paused mid-gate ({banked} rows banked); "
                  f"inspect {output}")
            return 7
        gate_record = checkpoint.get("instance_gate") or {}
        write_json(output / "gate_phase_checkpoint.json", {
            "provider_free_validation_complete": True,
            "gate_context_sha": gate_context_sha,
            "gated_case_count": gate_record.get("gated_case_count"),
            "compile_only_case_count": gate_record.get("compile_only_case_count"),
        })

        # This mode exercises the same generation and exact-instance gates as
        # the campaign but deliberately exits before Docker checks, credentials,
        # compatibility probes, or any provider request. It is suitable for a
        # zero-spend CI rehearsal of the gate phase.
        if args.gates_only or profile.get("gate_only") is True:
            report = _add_omissions_to_report({
                "schema_version": 1,
                "event": "atria_covering_campaign",
                "status": "gate_passed",
                "pause_reason": None,
                "resumable": False,
                "provider_calls": 0,
                "provider_phase_started": False,
                "gated_case_count": gate_record.get("gated_case_count"),
                "compile_only_case_count": gate_record.get("compile_only_case_count"),
                "gate_context_sha": gate_context_sha,
            }, manifest)
            write_json(output / "campaign_report.json", report)
            print(
                f"{profile['provider']} provider-free gates passed; gate-only mode made no provider calls. "
                f"Inspect {output}"
            )
            return 0

        # A profile change alone must never make an ordinary local invocation
        # billable.  Provider access needs --allow-provider, an explicit
        # dispatch of the named deployed campaign workflow, or a paid intent
        # staged by one of those starts. Keep this before Docker and credential
        # inspection so there is one auditable no-provider boundary.
        if not provider_access_allowed:
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "schema_version": 1,
                "event": "atria_covering_campaign",
                "status": "prepared",
                "pause_reason": "provider_access_not_explicitly_allowed",
                "resumable": False,
                "provider_calls": 0,
                "provider_phase_started": False,
                "gated_case_count": gate_record.get("gated_case_count"),
                "compile_only_case_count": gate_record.get("compile_only_case_count"),
                "gate_context_sha": gate_context_sha,
            }, manifest))
            _mark_terminal(
                output,
                "provider_access_not_explicitly_allowed",
                "the exact-instance gates passed, but no explicit paid authorization was supplied; "
                "no credential, Docker, compatibility, or provider operation was attempted",
            )
            print(
                "Campaign gates passed but provider access was not explicitly authorized; "
                "no provider call was made. Re-run with --allow-provider or dispatch the campaign workflow."
            )
            return 3

        # Persist the authorization in state before any paid-side operation.
        # Scheduled resumes refuse checkpoints without this marker, so a state
        # created by a provider-free run can never become billable merely
        # because a workflow or profile later changes.
        checkpoint.setdefault("run", {})["provider_access_explicitly_allowed"] = True
        checkpoint["run"]["provider_access_authorized_at"] = _utc_now()
        write_json(output / "suite_checkpoint.json", checkpoint)

        runtime = _runtime_check()
        write_json(output / "runtime.json", runtime)
        if not runtime.get("available", False):
            runtime_failures = int(checkpoint.get("runtime_failures", 0) or 0) + 1
            checkpoint["runtime_failures"] = runtime_failures
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = (
                "docker_unavailable"
                if runtime_failures <= 3
                else "docker_unavailable_retries_exhausted"
            )
            write_json(output / "suite_checkpoint.json", checkpoint)
            resumable = checkpoint["pause_reason"] == "docker_unavailable"
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "paused" if resumable else "blocked",
                "pause_reason": checkpoint["pause_reason"],
                "resumable": resumable,
                "runtime_failures": runtime_failures,
            }, manifest))
            if not resumable:
                _mark_terminal(
                    output,
                    "docker_unavailable_retries_exhausted",
                    "Docker remained unavailable for all three automatic scheduled retries; "
                    "no provider credential or provider call was made",
                )
            print(
                "Campaign paused for automatic Docker retry" if resumable
                else "Campaign stopped after bounded Docker retries"
            )
            return 8 if resumable else 4

        credentials = _optional_credentials(profile)
        api_key_env = str(profile["api_key_env"])
        credential_pause_reason = f"waiting_for_private_{api_key_env}"
        write_json(output / "credential_check.json", {
            "configured": credentials is not None,
            "provider": profile["provider"],
            "api_key_env": api_key_env,
        })
        if credentials is None:
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "prepared", "pause_reason": credential_pause_reason,
                "resumable": False,
            }, manifest))
            _mark_terminal(output, credential_pause_reason,
                           "no provider call was made; configure the named Actions secret "
                           "and re-dispatch manually")
            print(f"Campaign validated with no provider call; configure {api_key_env} privately.")
            return 3

        # Phase 2: the paid compatibility probe, with outage patience bounded
        # by the remaining job budget.
        compat_deadline = started + job_seconds - max(300.0, patience * 0)
        compatibility, compat_waited = _compatibility_with_patience(
            profile, credentials, output,
            patience_seconds=patience,
            backoff_seconds=backoff,
            deadline=compat_deadline,
        )
        if compatibility.get("status") != "passed":
            pause_reason = (
                "provider_infrastructure_error_compatibility"
                if compatibility.get("error_type") == "provider_transient"
                else "completion_compatibility_failed"
            )
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = pause_reason
            checkpoint["run"]["compatibility"] = {
                "status": compatibility.get("status"),
                "error_type": compatibility.get("error_type"),
                "waited_seconds": round(compat_waited, 1),
            }
            write_json(output / "suite_checkpoint.json", checkpoint)
            write_json(output / "campaign_report.json", _add_omissions_to_report(
                _report_from_checkpoint(
                    checkpoint, compatibility=compatibility, compat_waited=compat_waited,
                    status="paused", pause_reason=pause_reason,
                ), manifest,
            ))
            if pause_reason == "completion_compatibility_failed":
                # Substantive compat failure is a model/API change, not a
                # transient: the supervisor must not auto-resume it.
                _mark_terminal(output, pause_reason,
                               "compatibility probe completed but the model "
                               "did not answer READY")
            print(f"Campaign paused after compatibility check; inspect {output}")
            return 7

        # Phase 3: the episodes.  Wall budget is what remains of the job.
        remaining_wall = max(60.0, job_seconds - (time.monotonic() - started))
        checkpoint = run_suite(
            manifest, max_wall_seconds=remaining_wall, **scheduler_kwargs
        )
        status = "paused" if checkpoint.get("paused") else "completed"
        pause_reason = checkpoint.get("pause_reason")
        report = _report_from_checkpoint(
            checkpoint, compatibility=compatibility, compat_waited=compat_waited,
            status=status, pause_reason=pause_reason,
        )
        _add_omissions_to_report(report, manifest)
        report["remaining_job_seconds"] = round(job_seconds - (time.monotonic() - started), 1)
        write_json(output / "campaign_report.json", report)
        print(f"{profile['provider']} campaign {status}; inspect {output}")
        return 0 if status == "completed" else 8
    except (OSError, RuntimeError, ValueError, DockerBackendError) as exc:
        diagnostics = _campaign_failure_diagnostics(output)
        def _failure_report(value: dict[str, Any]) -> dict[str, Any]:
            if profile:
                _add_omissions_to_report(value, {"campaign": _campaign_metadata(profile)})
            return value
        detail = redact_text(str(exc)) + _format_failure_diagnostics(diagnostics)
        # Host/Docker I/O failures can happen outside run_suite's per-case
        # handler. They get the same bounded automatic restart treatment; a
        # validation/configuration exception remains terminal and recorded.
        transient = isinstance(exc, (OSError, DockerBackendError))
        checkpoint_path = output / "suite_checkpoint.json"
        checkpoint = _load_report_file(checkpoint_path)
        wrapper_retry_path = output / "wrapper_transient_retry.json"
        retry_record = _load_report_file(wrapper_retry_path)
        transient_failures = max(
            int(checkpoint.get("wrapper_transient_failures", 0) or 0),
            int(retry_record.get("failures", 0) or 0),
        ) + 1
        if transient and transient_failures <= 3:
            try:
                output.mkdir(parents=True, exist_ok=True)
                if checkpoint:
                    checkpoint["wrapper_transient_failures"] = transient_failures
                    checkpoint["paused"] = True
                    checkpoint["pause_reason"] = "wrapper_transient_error"
                    checkpoint["updated_at"] = _utc_now()
                    write_json(checkpoint_path, checkpoint)
                write_json(wrapper_retry_path, {
                    "failures": transient_failures,
                    "updated_at": _utc_now(),
                })
                write_json(output / "campaign_report.json", _failure_report({
                    "schema_version": 1,
                    "event": "covering_campaign",
                    "status": "paused",
                    "pause_reason": "wrapper_transient_error",
                    "resumable": True,
                    "wrapper_transient_failures": transient_failures,
                    "detail": detail,
                    "diagnostics": diagnostics,
                    "updated_at": _utc_now(),
                }))
            except OSError:
                pass
            print(f"{profile.get('provider', 'covering campaign')} campaign paused for automatic transient-wrapper retry: {detail}")
            return 8
        if diagnostics["generation_preflight_failed_cases"]:
            pause_reason = "generation_preflight_failed"
            provider_calls: int | None = 0
        elif diagnostics["exact_instance_failed_cases"]:
            pause_reason = "instance_oracle_coverage_incomplete"
            provider_calls = 0
        elif transient:
            pause_reason = "wrapper_transient_retries_exhausted"
            provider_calls = None
        else:
            pause_reason = "wrapper_exception"
            provider_calls = None
        try:
            output.mkdir(parents=True, exist_ok=True)
            write_json(output / "wrapper_failed.json", {
                "pause_reason": pause_reason,
                "detail": detail,
                "diagnostics": diagnostics,
                "recorded_at": _utc_now(),
            })
            write_json(output / "campaign_report.json", _failure_report({
                "schema_version": 1,
                "event": "covering_campaign",
                "status": "blocked",
                "pause_reason": pause_reason,
                "resumable": False,
                "provider_calls": provider_calls,
                "detail": detail,
                "diagnostics": diagnostics,
                "updated_at": _utc_now(),
            }))
        except OSError:
            pass
        print(f"{profile.get('provider', 'covering campaign')} campaign failed: {detail}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
