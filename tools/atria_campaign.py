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
   outage patience; anything longer pauses the campaign with a resumable
   checkpoint (``pause_reason`` in {provider_error, max_wall_seconds}) that
   the supervisor workflow resumes.  Budget ceilings and infrastructure
   failures pause non-resumably and wait for an operator.

Exit codes: 0 completed; 2 blocked or unexpected error; 3 no credentials;
4 Docker unavailable; 7 compatibility paused; 8 suite paused or incomplete.
"""
from __future__ import annotations

import argparse
import json
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


def _validate_campaign_profile(profile: Mapping[str, Any]) -> None:
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


def _mark_terminal(output: Path, reason: str, detail: str) -> None:
    """Record a non-resumable end so the supervisor stops instead of
    restarting a deterministically failing wrapper forever.  The marker is
    cleared at the start of every run, so the supervisor allows exactly one
    automatic restart and a human decision after that."""
    try:
        write_json(output / "wrapper_failed.json", {
            "pause_reason": reason,
            "detail": redact_text(detail),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "experiments" / "atria_campaign.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "atria_campaign")
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args(argv)
    output = args.out
    try:
        # A terminal-failure marker from a previous dispatch is cleared at
        # the start of every run: one automatic restart is allowed, a repeat
        # failure rewrites it and the supervisor stands down for an operator.
        marker = output / "wrapper_failed.json"
        marker.unlink(missing_ok=True)
        started = time.monotonic()
        profile = _load_yaml(args.profile)
        _validate_campaign_profile(profile)
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
            write_json(marker, {
                "pause_reason": "gate_case_repeatedly_blocked",
                "detail": redact_text(str(exc)),
                "recorded_at": _utc_now(),
            })
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "blocked",
                "pause_reason": "gate_case_repeatedly_blocked",
                "resumable": False,
                "detail": redact_text(str(exc)),
                "compile_only_disclaimer": (
                    "compile_only rows are graded by judges without a "
                    "behavioral reference on that exact instance; they do "
                    "not carry the exact-instance oracle guarantee and must "
                    "not be read as validated model verdicts"
                ),
            }, manifest))
            print(f"Campaign blocked: a gate case failed validation twice; "
                  f"inspect {output}")
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
        write_json(output / "gate_phase_checkpoint.json", {
            "provider_free_validation_complete": True,
            "gate_context_sha": gate_context_sha,
            "gated_case_count": (checkpoint.get("instance_gate") or {}).get("gated_case_count"),
            "compile_only_case_count": (checkpoint.get("instance_gate") or {}).get("compile_only_case_count"),
        })

        runtime = _runtime_check()
        write_json(output / "runtime.json", runtime)
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
        if not runtime.get("available", False):
            checkpoint["paused"] = True
            checkpoint["pause_reason"] = str(runtime.get("reason", "docker_unavailable"))
            write_json(output / "suite_checkpoint.json", checkpoint)
            write_json(output / "campaign_report.json", _add_omissions_to_report({
                "status": "prepared", "pause_reason": checkpoint["pause_reason"],
                "resumable": False,
            }, manifest))
            _mark_terminal(output, str(runtime.get("reason", "docker_unavailable")),
                           "Docker unavailable; no provider call was made")
            print(f"Campaign prepared but Docker is unavailable; no provider call: {output}")
            return 4

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
        detail = redact_text(str(exc))
        try:
            write_json(output / "wrapper_failed.json", {
                "pause_reason": "wrapper_exception",
                "detail": detail,
                "recorded_at": _utc_now(),
            })
        except OSError:
            pass
        print(f"atria_campaign failed: {detail}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
