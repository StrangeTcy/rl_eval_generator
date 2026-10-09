"""Versioned per-attempt records for staged episode outcomes.

The record supplements ``final.json`` and existing trace/API artifacts; it does
not replace or reinterpret their raw values. Stage statuses come from explicit
judge outcomes or observable host/judge events, never from the legacy
``failure_mode`` label.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

STAGE_NAMES = (
    "provider_transport",
    "response_parsing",
    "patch_validation",
    "required_artifacts",
    "source_validation",
    "runtime_execution",
    "judge_execution",
    "behavioral_evaluation",
)

# ``scored`` means behavioral evaluation ran; ``rejected`` means a protocol,
# patch, artifact, or source stage rejected the submission first; ``unscored``
# means execution/provider/judge evidence is insufficient for behavior scoring.
_EARLY_REJECTION_STAGES = (
    "response_parsing",
    "patch_validation",
    "required_artifacts",
    "source_validation",
)


def _outcome(status: str, code: str | None = None, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if code is not None:
        result["code"] = code
    result.update(details)
    return result


def _events(final: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = final.get("events")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _event_seen(
    events: Sequence[Mapping[str, Any]],
    actions: set[str],
    statuses: set[str],
) -> bool:
    return any(
        str(event.get("action", "")).lower() in actions
        and str(event.get("status", "")).lower() in statuses
        for event in events
    )


def _event_text(final: Mapping[str, Any]) -> str:
    pieces: list[str] = []
    notes = final.get("notes")
    if isinstance(notes, list):
        pieces.extend(str(note) for note in notes)
    for event in _events(final):
        summary = event.get("summary")
        if isinstance(summary, str):
            pieces.append(summary)
    return " ".join(pieces)


def _explicit_stage(final: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    outcomes = final.get("stage_outcomes")
    if not isinstance(outcomes, Mapping):
        return None
    value = outcomes.get(name)
    if not isinstance(value, Mapping):
        return None
    status = value.get("status")
    if not isinstance(status, str) or not status:
        return None
    # Keep stage payloads structured and bounded; free-form detail text remains
    # available in final.json and is not treated as a causal diagnosis here.
    copied: dict[str, Any] = {"status": status[:64]}
    code = value.get("code")
    if isinstance(code, str):
        copied["code"] = code[:128]
    for key in ("successful_responses", "errors", "valid_actions", "invalid_attempts"):
        count = value.get(key)
        if isinstance(count, (int, float)) and not isinstance(count, bool):
            copied[key] = count
    missing_files = value.get("missing_files")
    if isinstance(missing_files, list):
        copied["missing_files"] = [str(item)[:256] for item in missing_files[:100]]
    return copied


def _mark_not_reached(stages: dict[str, dict[str, Any]], names: Sequence[str]) -> None:
    for name in names:
        if stages[name].get("status") == "unknown":
            stages[name] = _outcome("not_reached")


def _checks(final: Mapping[str, Any]) -> Mapping[str, Any]:
    value = final.get("checks")
    return value if isinstance(value, Mapping) else {}


def _metrics(final: Mapping[str, Any]) -> Mapping[str, Any]:
    value = final.get("metrics")
    return value if isinstance(value, Mapping) else {}


def _stage_from_host_events(
    final: Mapping[str, Any],
    traces: Sequence[Mapping[str, Any]],
    model_responses: Sequence[Mapping[str, Any]],
    api_errors: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build stage states from explicit stage outcomes and observable events.

    An explicit ``stage_outcomes`` object emitted by a judge takes precedence.
    Legacy ``failure_mode`` is intentionally not consulted for classification;
    an absent signal remains ``unknown`` or ``not_reached``.
    """
    checks = _checks(final)
    metrics = _metrics(final)
    events = _events(final)
    stages = {name: _outcome("unknown") for name in STAGE_NAMES}

    # Provider requests/responses are recorded by the host in separate files.
    response_count = len(model_responses)
    api_error_count = len(api_errors)
    if response_count and api_error_count:
        provider = _outcome(
            "completed_with_errors",
            successful_responses=response_count,
            errors=api_error_count,
        )
    elif response_count:
        provider = _outcome("passed", successful_responses=response_count, errors=0)
    elif api_error_count:
        error_type = api_errors[-1].get("error_type")
        provider = _outcome(
            "failed",
            str(error_type)[:128] if isinstance(error_type, str) else "provider_error",
            successful_responses=0,
            errors=api_error_count,
        )
    else:
        provider = _outcome("unknown")
    stages["provider_transport"] = provider
    explicit = _explicit_stage(final, "provider_transport")
    if explicit is not None:
        stages["provider_transport"] = explicit

    valid_actions = sum(1 for row in traces if row.get("parsed_action") is not None)
    invalid_action_attempts = sum(
        int(row.get("invalid_action_attempts", 0) or 0)
        for row in traces
        if isinstance(row.get("invalid_action_attempts", 0), (int, float))
        and not isinstance(row.get("invalid_action_attempts", 0), bool)
    )
    parse_error_rows = sum(
        1
        for row in traces
        if row.get("parse_error")
        and row.get("parsed_action") is None
        and row.get("raw_model_output") is not None
    )
    if valid_actions:
        parsing = _outcome(
            "recovered" if parse_error_rows or invalid_action_attempts else "passed",
            "action_parsed",
            valid_actions=valid_actions,
            invalid_attempts=invalid_action_attempts,
        )
    elif response_count and (parse_error_rows or invalid_action_attempts):
        parsing = _outcome(
            "failed",
            "malformed_action",
            invalid_attempts=invalid_action_attempts,
        )
    elif stages["provider_transport"]["status"] == "failed":
        parsing = _outcome("not_reached")
    else:
        parsing = _outcome("unknown")
    stages["response_parsing"] = parsing
    explicit = _explicit_stage(final, "response_parsing")
    if explicit is not None:
        stages["response_parsing"] = explicit

    text = _event_text(final)
    if _event_seen(events, {"patch_missing"}, {"fail", "failed", "error"}):
        patch = _outcome("failed", "missing_patch")
    elif _event_seen(events, {"patch_invalid"}, {"fail", "failed", "error"}):
        patch = _outcome("failed", "patch_rejected")
    elif _event_seen(events, {"patch_valid"}, {"ok", "passed", "success"}) or checks.get("patch_valid") is True:
        patch = _outcome("passed", "patch_applied")
    elif checks.get("patch_found") is True and checks.get("patch_valid") is False:
        patch = _outcome("failed", "patch_rejected")
    else:
        patch = _outcome("unknown")
    stages["patch_validation"] = patch
    explicit_patch = _explicit_stage(final, "patch_validation")
    if explicit_patch is not None:
        stages["patch_validation"] = explicit_patch

    missing_required = metrics.get("missing_required_files")
    required_edit = checks.get("required_multifile_edit")
    if _event_seen(events, {"answer_format_invalid"}, {"fail", "failed", "error"}):
        code = "required_file_missing" if "not found" in text.lower() else "answer_artifact_invalid"
        required = _outcome("failed", code)
    elif required_edit is False or (isinstance(missing_required, list) and missing_required):
        required = _outcome(
            "failed",
            "required_file_missing",
            missing_files=deepcopy(missing_required) if isinstance(missing_required, list) else [],
        )
    elif (
        required_edit is True
        or checks.get("artifact_found") is True
        or (isinstance(missing_required, list) and not missing_required)
    ):
        required = _outcome("passed", "required_artifacts_present")
    else:
        required = _outcome("unknown")
    stages["required_artifacts"] = required
    explicit = _explicit_stage(final, "required_artifacts")
    if explicit is not None:
        stages["required_artifacts"] = explicit
    if explicit_patch is None and (
        required_edit is not None or isinstance(missing_required, list)
    ):
        # A required-file diff can only be calculated after a valid patch was
        # parsed and applied, even when the environment-specific judge predates
        # standardized patch stage outcomes.
        stages["patch_validation"] = _outcome("passed", "patch_applied")

    if _event_seen(events, {"source_invalid"}, {"fail", "failed", "error"}):
        code = "syntax_error" if "syntaxerror" in text.lower() or "syntax error" in text.lower() else "source_rejected"
        source = _outcome("failed", code)
    elif _event_seen(events, {"sources_valid"}, {"ok", "passed", "success"}) or checks.get("sources_valid") is True:
        source = _outcome("passed", "sources_accepted")
    elif checks.get("patch_valid") is True and checks.get("sources_valid") is False:
        source = _outcome("failed", "source_rejected")
    else:
        source = _outcome("unknown")
    stages["source_validation"] = source
    explicit = _explicit_stage(final, "source_validation")
    if explicit is not None:
        stages["source_validation"] = explicit

    if _event_seen(events, {"training_failed", "runtime_error", "timeout"}, {"fail", "failed", "error"}):
        runtime = _outcome("failed", "runtime_failure")
    elif checks.get("training_completed") is True:
        runtime = _outcome("passed", "runtime_completed")
    else:
        runtime = _outcome("unknown")
    stages["runtime_execution"] = runtime
    explicit = _explicit_stage(final, "runtime_execution")
    if explicit is not None:
        stages["runtime_execution"] = explicit

    scored_event = _event_seen(events, {"scored"}, {"ok", "passed", "success"})
    has_judge_payload = (
        bool(events)
        or isinstance(final.get("stage_outcomes"), Mapping)
        or isinstance(final.get("checks"), Mapping)
    )
    if _event_seen(events, {"judge_runtime_error", "reward_denial"}, {"fail", "failed", "error"}):
        judge = _outcome("failed", "judge_execution_failure")
    elif scored_event:
        judge = _outcome("passed", "judge_emitted_score")
    elif has_judge_payload:
        judge = _outcome("passed", "judge_result_emitted")
    else:
        judge = _outcome("unknown")
    stages["judge_execution"] = judge
    explicit = _explicit_stage(final, "judge_execution")
    if explicit is not None:
        stages["judge_execution"] = explicit

    if stages["provider_transport"].get("status") == "failed":
        _mark_not_reached(stages, ("response_parsing", "patch_validation", "required_artifacts", "source_validation", "runtime_execution", "judge_execution"))
    elif stages["response_parsing"].get("status") == "failed":
        _mark_not_reached(stages, ("patch_validation", "required_artifacts", "source_validation", "runtime_execution"))
    elif stages["patch_validation"].get("status") == "failed":
        _mark_not_reached(stages, ("required_artifacts", "source_validation", "runtime_execution"))
    elif stages["source_validation"].get("status") == "failed":
        _mark_not_reached(stages, ("runtime_execution",))
    elif stages["runtime_execution"].get("status") == "failed":
        _mark_not_reached(stages, ("judge_execution",))

    verdict = final.get("verdict")
    if scored_event and isinstance(verdict, str) and verdict in {"PASS", "FAIL"}:
        behavioral = _outcome(
            "scored_pass" if verdict == "PASS" else "scored_fail",
            "judge_scored",
        )
    elif any(stages[name].get("status") == "failed" for name in (
        "provider_transport",
        "response_parsing",
        "patch_validation",
        "required_artifacts",
        "source_validation",
        "runtime_execution",
        "judge_execution",
    )):
        behavioral = _outcome("not_reached")
    else:
        behavioral = _outcome("unknown")
    stages["behavioral_evaluation"] = behavioral
    explicit = _explicit_stage(final, "behavioral_evaluation")
    if explicit is not None:
        stages["behavioral_evaluation"] = explicit
    if (
        stages["judge_execution"].get("status") == "unknown"
        and stages["behavioral_evaluation"].get("status") in {"scored_pass", "scored_fail"}
    ):
        stages["judge_execution"] = _outcome("passed", "behavioral_score_emitted")
    return stages


def build_attempt_record(
    *,
    attempt_id: str,
    case_id: str,
    campaign_id: str | None,
    environment: str,
    difficulty: str,
    seed: int,
    judge_guarantee: str | None,
    final: Mapping[str, Any],
    traces: Sequence[Mapping[str, Any]] = (),
    model_responses: Sequence[Mapping[str, Any]] = (),
    api_errors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create an additive, versioned record for one runner attempt."""
    stages = _stage_from_host_events(final, traces, model_responses, api_errors)
    behavioral_status = stages["behavioral_evaluation"].get("status")
    if behavioral_status in {"scored_pass", "scored_fail"}:
        disposition = "scored"
    elif any(stages[name].get("status") == "failed" for name in _EARLY_REJECTION_STAGES):
        disposition = "rejected"
    else:
        disposition = "unscored"
    verdict = final.get("verdict")
    end_to_end_status = "passed" if verdict == "PASS" else "failed" if verdict == "FAIL" else "unobserved"

    score_keys = (
        "verdict",
        "score",
        "raw_accuracy",
        "accuracy_bin",
        "passed_checks",
        "checks",
        "metrics",
    )
    raw_scores = {key: deepcopy(final[key]) for key in score_keys if key in final}
    notes = final.get("notes")
    diagnostics = {
        "notes": deepcopy(notes) if isinstance(notes, list) else [],
        "judge_events": deepcopy(final.get("events")) if isinstance(final.get("events"), list) else [],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "episode_attempt",
        "campaign_id": campaign_id,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "environment": environment,
        "difficulty": difficulty,
        "seed": seed,
        "case_disposition": disposition,
        "end_to_end_status": end_to_end_status,
        # Legacy diagnostic retained for compatibility; stage classification
        # above never reads this field.
        "failure_mode": final.get("failure_mode"),
        "judge_guarantee": judge_guarantee,
        "stages": stages,
        # Copy raw score/check fields verbatim. No normalization or conflict
        # resolution is performed here.
        "raw_scores": raw_scores,
        "diagnostics": diagnostics,
    }


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read object rows from a JSONL artifact, ignoring malformed lines."""
    file_path = Path(path)
    if not file_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def stage_status_summary(record: Mapping[str, Any]) -> dict[str, str]:
    stages = record.get("stages")
    if not isinstance(stages, Mapping):
        return {}
    return {
        str(name): str(value.get("status", "unknown"))
        for name, value in stages.items()
        if isinstance(value, Mapping)
    }


__all__ = [
    "SCHEMA_VERSION",
    "STAGE_NAMES",
    "build_attempt_record",
    "read_jsonl",
    "stage_status_summary",
]
