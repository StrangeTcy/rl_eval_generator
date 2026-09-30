#!/usr/bin/env python3
"""Run the resilient Atria covering campaign: every environment, every level.

The campaign evaluates the pinned model across the covering difficulty matrix
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
from arena.secrets import redact_text  # noqa: E402
from tools.atria_first_experiment import (  # noqa: E402
    APPROVED_BASE,
    APPROVED_MODEL,
    _compatibility_check,
    _optional_credentials,
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


def _record_campaign_intent(
    output: Path,
    manifest: Mapping[str, Any],
    *,
    execution_mode: str,
    gate_context_sha: str | None,
) -> dict[str, Any]:
    """Persist the only continuation authority a scheduled run may trust.

    It is written before the long exact-instance gate, which may span several
    jobs. A schedule tick uses this small, non-secret record to decide whether
    it should resume provider-free gating or the explicitly requested paid
    phase; it never infers permission from a profile or the presence of a key.
    """
    if execution_mode not in {"gates_only", "paid"}:
        raise ValueError(f"invalid campaign execution mode: {execution_mode}")
    path = output / "campaign_intent.json"
    expected = {
        "schema_version": 1,
        "provider": "atria",
        "execution_mode": execution_mode,
        "case_manifest_sha256": _manifest_cases_sha256(manifest),
        "gate_context_sha": gate_context_sha,
    }
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = None
    if isinstance(existing, dict):
        comparable = {key: existing.get(key) for key in expected}
        if comparable != expected:
            raise ValueError(
                "campaign intent differs from the restored state; refuse to "
                "continue with a changed mode, manifest, or code context"
            )
        return existing
    value = {**expected, "recorded_at": _utc_now()}
    write_json(path, value)
    return value


def _restored_paid_authorization(output: Path) -> bool:
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
        and intent.get("provider") == "atria"
        and intent.get("execution_mode") == "paid"
    )


def _is_explicit_actions_paid_dispatch() -> bool:
    """Recognize the already-deployed campaign launcher's manual approval.

    The deployed workflow predates the newer ``--allow-provider`` argument,
    but a human ``workflow_dispatch`` of the named campaign workflow is an
    explicit paid start.  This compatibility path is intentionally limited to
    that workflow; local calls and arbitrary Actions jobs still need the flag.
    """
    return (
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and os.environ.get("GITHUB_WORKFLOW") == "Atria covering campaign"
    )


def _validate_campaign_profile(profile: Mapping[str, Any]) -> None:
    # Rehearsal mode: provider custom, no real API calls, exercises checkpoint resume
    if profile.get("provider") == "custom" and profile.get("name") in {"rehearsal", "rehearsal_autonomous"}:
        # Minimal checks for rehearsal: allow custom provider, any api_base, model offline/pinned
        if profile.get("api_key_env") not in {"REHEARSAL_API_KEY", "ATRIA_API_KEY", "CUSTOM_API_KEY"}:
            raise ValueError("rehearsal profile must use REHEARSAL_API_KEY or similar")
        # Skip strict atria checks for rehearsal
        return
    if profile.get("provider") != "atria":
        raise ValueError("campaign profile must pin provider: atria")
    if profile.get("model") != APPROVED_MODEL or profile.get("api_base") != APPROVED_BASE:
        raise ValueError(
            f"campaign profile must pin model {APPROVED_MODEL!r} and api_base {APPROVED_BASE!r}"
        )
    if profile.get("api_key_env") != "ATRIA_API_KEY":
        raise ValueError("campaign profile must use api_key_env: ATRIA_API_KEY")
    matrix = profile.get("matrix") or {}
    if matrix.get("mode") != "covering":
        raise ValueError("campaign profile must declare matrix.mode: covering")
    if matrix.get("seeds") != [0]:
        raise ValueError("campaign profile must declare matrix.seeds: [0]")
    resilience = profile.get("resilience") or {}
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
    for field in (
        "max_steps", "max_tokens", "invalid_retries", "max_retries",
        "max_api_calls", "max_tokens_total", "max_http_attempts",
    ):
        if field not in limits:
            raise ValueError(f"campaign profile limits miss {field}")
    rate = profile.get("rate_limit") or {}
    if not isinstance(rate.get("min_interval_seconds"), (int, float)) or rate.get("min_interval_seconds", 0) <= 0:
        raise ValueError("rate_limit.min_interval_seconds must be > 0")


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
        "event": "atria_covering_campaign",
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
    if profile.get("provider") != "atria":
        return False, "non-atria profile keeps its output directory"
    if explicit_fresh:
        return True, "explicit --fresh"
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
        job_seconds = int(profile["campaign_job_seconds"])
        patience = float(resilience["provider_outage_patience_seconds"])
        backoff = float(resilience["provider_outage_backoff_seconds"])

        manifest = build_manifest(root=ROOT, matrix="covering", seeds=[0])
        _apply_gate_blocked_exclusions(manifest, profile)
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "pilot_manifest.json", manifest)
        modality = inventory_selected_modalities(manifest, root=ROOT)
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
                "provider": "atria",
                "provider_input_modality": "text_only",
            }
            write_json(output / "pilot_manifest.json", manifest)
            modality = inventory_selected_modalities(manifest, root=ROOT)
        # Budget exhaustion and floor effects pause non-resuably, so the
        # validated cases must complete before the compile-only ones.
        _order_cases_referenced_first(manifest)
        write_json(output / "pilot_manifest.json", manifest)
        write_json(output / "modality_inventory.json", modality)
        if not modality["all_selected_cases_text_only_compatible"]:
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "blocked", "pause_reason": "unsupported_non_text_input_for_atria",
                "resumable": False,
            }, manifest))
            _mark_terminal(output, "unsupported_non_text_input_for_atria",
                           "provider cannot serve the selected cases")
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
                or _is_explicit_actions_paid_dispatch()
                or _restored_paid_authorization(output)
            )
        )
        execution_mode = "paid" if provider_access_allowed else "gates_only"
        _record_campaign_intent(
            output,
            manifest,
            execution_mode=execution_mode,
            gate_context_sha=gate_context_sha,
        )
        scheduler_kwargs: dict[str, Any] = {
            "output_dir": output,
            "provider": "atria",
            "model": APPROVED_MODEL,
            "api_key_env": "ATRIA_API_KEY",
            "api_base": APPROVED_BASE,
            "sandbox": "docker",
            "max_steps": int(limits["max_steps"]),
            "max_tokens": int(limits["max_tokens"]),
            "temperature": float(profile["temperature"]),
            "top_p": float(profile["top_p"]),
            "invalid_retries": int(limits["invalid_retries"]),
            "max_retries": int(limits["max_retries"]),
            "max_http_attempts": int(limits["max_http_attempts"]),
            "provider_min_interval_seconds": float(profile["rate_limit"]["min_interval_seconds"]),
            "max_api_calls": int(limits["max_api_calls"]),
            "max_tokens_total": int(limits["max_tokens_total"]),
            "min_interval_seconds": float(profile["rate_limit"]["min_interval_seconds"]),
            "floor_effect_after": int(limits.get("floor_effect_after", 0)),
            "request_extra": {},
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
                "Atria provider-free gates passed; gate-only mode made no provider calls. "
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
        write_json(output / "credential_check.json", {
            "configured": credentials is not None,
            "api_key_env": "ATRIA_API_KEY",
        })
        if credentials is None:
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "prepared", "pause_reason": "waiting_for_private_ATRIA_API_KEY",
                "resumable": False,
            }, manifest))
            _mark_terminal(output, "waiting_for_private_ATRIA_API_KEY",
                           "no provider call was made; configure the secret "
                           "and re-dispatch manually")
            print("Campaign validated with no provider call; configure ATRIA_API_KEY privately.")
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
        print(f"Atria campaign {status}; inspect {output}")
        return 0 if status == "completed" else 8
    except (OSError, RuntimeError, ValueError, DockerBackendError) as exc:
        diagnostics = _campaign_failure_diagnostics(output)
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
                write_json(output / "campaign_report.json", {
                    "schema_version": 1,
                    "event": "atria_covering_campaign",
                    "status": "paused",
                    "pause_reason": "wrapper_transient_error",
                    "resumable": True,
                    "wrapper_transient_failures": transient_failures,
                    "detail": detail,
                    "diagnostics": diagnostics,
                    "updated_at": _utc_now(),
                })
            except OSError:
                pass
            print(f"atria_campaign paused for automatic transient-wrapper retry: {detail}")
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
            write_json(output / "campaign_report.json", {
                "schema_version": 1,
                "event": "atria_covering_campaign",
                "status": "blocked",
                "pause_reason": pause_reason,
                "resumable": False,
                "provider_calls": provider_calls,
                "detail": detail,
                "diagnostics": diagnostics,
                "updated_at": _utc_now(),
            })
        except OSError:
            pass
        print(f"atria_campaign failed: {detail}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
