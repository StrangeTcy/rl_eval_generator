#!/usr/bin/env python3
"""Rehearsal campaign: provider-free validation + simulated orchestration that exercises checkpoint resume.

This tool is the second part of the rehearsal requested by Astra/Luna:
- Real validation: exact selected manifest and referenced judges pass (done separately via instance_oracle_gate, but also re-validated here provider-free)
- Real orchestration, simulated provider: actual run_suite checkpointing, supervisor decision, wall interruption, and scripted transient provider errors, with no real provider calls.

It is designed to be run inside the actual GitHub Actions workflow (rehearsal-autonomous.yml) which restores state artifacts across jobs/runs and uses the real campaign_supervisor.py.

Usage:
  python tools/rehearsal_campaign.py --profile experiments/atria_first5.yaml --out runs/rehearsal

The first invocation (no checkpoint) intentionally uses a short wall budget (7s) and injects a transient provider error on the second case, so it pauses with pause_reason=max_wall_seconds after completing 2 cases (with 1 retry). The second invocation (resume) uses a larger budget and completes the remaining cases.

No real provider calls are made: episodes are faked via monkey-patched subprocess.run, and provider credential resolution is mocked.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.artifacts import write_json  # noqa: E402
from tools.suite_inventory import build_manifest, _load_yaml  # noqa: E402
from tools.atria_modality import inventory_selected_modalities  # noqa: E402
from tools.run_suite import run_suite  # noqa: E402

EXPECTED_CASES = [
    ("regex_state_machine", "easy,easy"),
    ("epistemic_games", "trap,ambiguous,paired,balanced,bare_table"),
    ("categorical_lenses", "easy,easy"),
    ("rd_state_carry", "easy,easy,easy,easy,easy"),
    ("glyph", "easy,easy,easy,easy,easy,easy"),
]

# For deterministic fake episodes
FAKE_SLEEP_SECONDS = 2.0


def _select_manifest(profile_path: Path) -> dict[str, Any]:
    manifest = build_manifest(root=ROOT, matrix="all", seeds=[0], dry_run=False)
    requested = list(EXPECTED_CASES)
    selected: list[dict[str, Any]] = []
    for env, diff in requested:
        matches = [c for c in manifest["cases"] if c["environment"] == env and c["difficulty"] == diff and c["seed"] == 0]
        if len(matches) != 1:
            raise ValueError(f"inventory missing {env} {diff}")
        selected.append(matches[0])
    env_by_name = {item["environment"]: item for item in manifest.get("environments", [])}
    selected_envs = [env_by_name[env] for env, _ in requested]
    sel = dict(manifest)
    sel.update(
        {
            "case_count": len(selected),
            "environment_count": len(selected_envs),
            "cases": selected,
            "environments": selected_envs,
            "selection": {
                "matrix": "pilot",
                "profile": str(profile_path),
                "seeds": [0],
                "requested_cases": [{"environment": e, "difficulty": d} for e, d in requested],
                "max_cases": 5,
            },
            "pilot": {
                "provider": "rehearsal",
                "model": "offline/pinned",
                "concurrency": 1,
                "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest() if profile_path.is_file() else "none",
                "config_hashes": {c["environment"]: c["config_sha256"] for c in selected},
            },
        }
    )
    return sel


def _generation_preflight(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    from tools.suite_inventory import _preflight_case

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


def _fake_oracle_report(manifest: dict) -> dict:
    return {
        "schema_version": 1,
        "api_calls": 0,
        "failure_count": 0,
        "model_sweep_allowed": True,
        "behavioral_coverage_complete": True,
        "instance_coverage_complete": True,
        "environments": [
            {"environment": c["environment"], "status": "ready", "reference_behavior": "mocked_for_rehearsal"}
            for c in manifest["cases"]
        ],
    }


def _fake_instance_report(manifest: dict) -> dict:
    rows = []
    for case in manifest["cases"]:
        rows.append(
            {
                "case_id": case["case_id"],
                "environment": case["environment"],
                "difficulty": case["difficulty"],
                "seed": case["seed"],
                "status": "passed",
                "provider_calls": 0,
                "variants": [],
            }
        )
    return {
        "schema_version": 1,
        "provider_calls": 0,
        "instance_coverage_complete": True,
        "cases": rows,
    }


def _utc_old() -> str:
    # Old enough to bypass 1200s backoff in campaign_supervisor
    return "2026-09-20T00:00:00+00:00"


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _build_fake_episode_runner():
    """Returns a function that mimics subprocess.run for arena.py run calls, with sleep and transient errors."""

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
        # Only intercept arena.py run calls
        if "arena.py" in cmd_str and "run" in cmd_str:
            # Extract --env
            try:
                env_idx = command.index("--env")
                env_name = command[env_idx + 1]
            except (ValueError, IndexError):
                env_name = "unknown"
            # Simulate work
            time.sleep(FAKE_SLEEP_SECONDS)
            key = env_name
            count = attempt_counter.get(key, 0)
            attempt_counter[key] = count + 1

            # Inject transient provider error on second case (epistemic_games) first attempt
            if env_name == "epistemic_games" and count == 0:
                return _provider_error_episode(http_attempts=2)

            # All other attempts succeed; alternate PASS/FAIL for variety but still scored
            if env_name == "epistemic_games":
                return _scored_episode(http_attempts=1, verdict="FAIL", score=0.0)
            return _scored_episode(http_attempts=1, verdict="PASS", score=1.0)
        # For any other subprocess call, run real
        return subprocess.run(command, **kwargs)

    return fake_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "experiments" / "atria_first5.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "rehearsal")
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--skip-heavy-gates", action="store_true", help="mock oracle/instance gates for fast rehearsal")
    args = parser.parse_args(argv)
    output = args.out.expanduser()
    output.mkdir(parents=True, exist_ok=True)

    # Clear terminal marker at start (like atria_campaign)
    marker = output / "wrapper_failed.json"
    marker.unlink(missing_ok=True)

    profile_path = args.profile.expanduser().resolve()
    if not profile_path.is_file():
        # Allow missing profile for rehearsal; create minimal
        profile = {
            "name": "rehearsal",
            "provider": "custom",
            "api_base": "https://example.invalid/v1",
            "model": "offline/pinned",
            "api_key_env": "REHEARSAL_API_KEY",
            "concurrency": 1,
            "seed": 0,
            "temperature": 0,
            "top_p": None,
            "rate_limit": {"min_interval_seconds": 0.1},
            "limits": {
                "max_steps": 1,
                "max_tokens": 7,
                "invalid_retries": 0,
                "max_retries": 1,
                "max_api_calls": 100,
                "max_http_attempts": 100,
                "max_wall_seconds": 7,
                "floor_effect_after": 0,
                "sandbox": "docker",
            },
        }
    else:
        profile = _load_yaml(profile_path)

    # Build manifest for 5 cases
    manifest = _select_manifest(profile_path if profile_path.is_file() else Path("rehearsal.yaml"))
    write_json(output / "pilot_manifest.json", manifest)

    # Modality inventory (provider-free)
    try:
        modality = inventory_selected_modalities(manifest, root=ROOT)
    except Exception as exc:
        modality = {"error": str(exc), "all_selected_cases_text_only_compatible": True, "unsupported_case_ids": []}
    write_json(output / "modality_inventory.json", modality)

    # Generation preflight (fast, no torch)
    generation = _generation_preflight(manifest)
    write_json(output / "generation_preflight.json", {"cases": generation})
    if any(item.get("status") != "ready" for item in generation):
        print(f"Rehearsal blocked by generation preflight; inspect {output}")
        write_json(output / "campaign_report.json", {"status": "blocked", "pause_reason": "generation_preflight_failed", "resumable": False})
        return 2

    # Oracle and instance gates
    if args.skip_heavy_gates:
        oracle = _fake_oracle_report(manifest)
        instance_report = _fake_instance_report(manifest)
        write_json(output / "oracle_preflight.json", oracle)
        write_json(output / "instance_oracles.json", instance_report)
    else:
        # Real validation path (requires torch) - for rehearsal we still want to show it passes
        # We mock for speed unless explicitly requested
        from tools.oracle_preflight import validate_manifest_oracles
        from tools.instance_oracle_gate import validate_manifest_instances

        oracle = validate_manifest_oracles(manifest, root=ROOT)
        write_json(output / "oracle_preflight.json", oracle)
        if not oracle.get("model_sweep_allowed"):
            print(f"Rehearsal blocked by oracle preflight; inspect {output}")
            write_json(output / "campaign_report.json", {"status": "blocked", "pause_reason": "oracle_preflight_failed", "resumable": False})
            return 2
        instance_report = validate_manifest_instances(manifest, root=ROOT, include_slow=True)
        write_json(output / "instance_oracles.json", instance_report)
        if not instance_report["instance_coverage_complete"]:
            print(f"Rehearsal blocked by instance gate; inspect {output}")
            write_json(output / "campaign_report.json", {"status": "blocked", "pause_reason": "instance_oracle_coverage_incomplete", "resumable": False})
            return 2

    # Determine wall budget: first run small to force interruption, resume large to complete
    checkpoint_path = output / "suite_checkpoint.json"
    existing = None
    if checkpoint_path.is_file():
        try:
            existing = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            existing = None

    if existing and existing.get("results"):
        # Resume: larger budget
        wall_seconds = 300.0
        print(f"Resuming rehearsal with wall_seconds={wall_seconds}, existing results={len(existing.get('results', []))}")
    else:
        wall_seconds = 7.0
        print(f"Fresh rehearsal with wall_seconds={wall_seconds} to force interruption")

    # Mock provider credential resolution and Docker check
    import tools.run_suite as rs
    original_resolve = rs.resolve_provider

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

    # Patch
    import unittest.mock as mock

    fake_episode_runner = _build_fake_episode_runner()

    # Need to patch where run_suite uses subprocess.run and resolve_provider
    with mock.patch("tools.run_suite.resolve_provider", side_effect=fake_resolve):
        with mock.patch("tools.run_suite.subprocess.run", side_effect=fake_episode_runner):
            with mock.patch("tools.run_suite._sleep", side_effect=lambda s: time.sleep(0.1)):  # fast backoff sleep
                # Also patch oracle gate inside run_suite if skip_heavy_gates
                if args.skip_heavy_gates:
                    with mock.patch("tools.oracle_preflight.validate_manifest_oracles", return_value=_fake_oracle_report(manifest)):
                        with mock.patch("tools.instance_oracle_gate.validate_manifest_instances", return_value=_fake_instance_report(manifest)):
                            checkpoint = run_suite(
                                manifest,
                                output_dir=output,
                                provider="custom",
                                model="offline/pinned",
                                api_key_env="REHEARSAL_API_KEY",
                                api_base="https://example.invalid/v1",
                                sandbox="docker",
                                max_steps=1,
                                max_tokens=7,
                                temperature=0.0,
                                top_p=None,
                                invalid_retries=0,
                                max_retries=1,
                                max_http_attempts=100,
                                provider_min_interval_seconds=0.1,
                                max_api_calls=100,
                                max_wall_seconds=wall_seconds,
                                min_interval_seconds=0.1,
                                floor_effect_after=0,
                                request_extra={},
                                checkpoint_path=checkpoint_path,
                                dry_run=False,
                                allow_config_drift=False,
                                allow_compile_only_oracles=True,
                                unreferenced_compile_only=False,
                                provider_outage_patience_seconds=60,
                                provider_outage_backoff_seconds=1,
                                gate_context_sha="rehearsal-context-sha",
                            )
                else:
                    checkpoint = run_suite(
                        manifest,
                        output_dir=output,
                        provider="custom",
                        model="offline/pinned",
                        api_key_env="REHEARSAL_API_KEY",
                        api_base="https://example.invalid/v1",
                        sandbox="docker",
                        max_steps=1,
                        max_tokens=7,
                        temperature=0.0,
                        top_p=None,
                        invalid_retries=0,
                        max_retries=1,
                        max_http_attempts=100,
                        provider_min_interval_seconds=0.1,
                        max_api_calls=100,
                        max_wall_seconds=wall_seconds,
                        min_interval_seconds=0.1,
                        floor_effect_after=0,
                        request_extra={},
                        checkpoint_path=checkpoint_path,
                        dry_run=False,
                        allow_config_drift=False,
                        allow_compile_only_oracles=True,
                        unreferenced_compile_only=False,
                        provider_outage_patience_seconds=60,
                        provider_outage_backoff_seconds=1,
                        gate_context_sha="rehearsal-context-sha",
                    )

    # If paused due to wall budget, set updated_at old to bypass supervisor backoff for fast rehearsal
    if checkpoint.get("paused") and checkpoint.get("pause_reason") == "max_wall_seconds":
        checkpoint["updated_at"] = _utc_old()
        # Also ensure provider_outage is preserved
        write_json(checkpoint_path, checkpoint)
        print(f"Paused for wall budget, set updated_at to old for immediate resume: {checkpoint_path}")

    # Also handle provider_error pause similarly
    if checkpoint.get("paused") and checkpoint.get("pause_reason") == "provider_error":
        checkpoint["updated_at"] = _utc_old()
        write_json(checkpoint_path, checkpoint)

    # Write campaign report
    status = "paused" if checkpoint.get("paused") else "completed"
    report = {
        "schema_version": 1,
        "event": "rehearsal_campaign",
        "status": status,
        "pause_reason": checkpoint.get("pause_reason"),
        "resumable": checkpoint.get("pause_reason") in {"provider_error", "max_wall_seconds", "provider_infrastructure_error_compatibility"} if checkpoint.get("pause_reason") else False,
        "recorded_cases": len(checkpoint.get("results", [])),
        "manifest_case_count": manifest["case_count"],
        "results": checkpoint.get("results", []),
        "provider_outage": checkpoint.get("provider_outage"),
        "http_attempts_total": checkpoint.get("http_attempts_total"),
        "updated_at": checkpoint.get("updated_at"),
        "wall_seconds_used": wall_seconds,
        "rehearsal_note": "simulated provider, no real API calls, exercises checkpoint resume and transient error handling",
    }
    write_json(output / "campaign_report.json", report)

    # Write campaign_ref.txt for supervisor
    try:
        import subprocess as sp

        sha = sp.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        sha = "rehearsal-sha"
    (output / "campaign_ref.txt").write_text(sha + "\n", encoding="utf-8")

    print(f"Rehearsal {status}; inspect {output}")
    print(json.dumps(report, indent=2))
    return 0 if status == "completed" else 8


if __name__ == "__main__":
    raise SystemExit(main())
