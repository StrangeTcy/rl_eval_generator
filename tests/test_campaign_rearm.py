"""Tests for the leg that asks for its own successor.

The behaviour that matters here is the negative one: a campaign must never be able to spin the
scheduler, stack a second leg on top of a running one, redden its own leg because a re-arm was
refused, or widen what it is authorized to bill. The cooldown, the 40-leg cap and the three stops
(cancelled leg, regressed state upload, terminal marker) are deliberately the same semantics the
Atria covering launcher's CHAIN already runs on, so this repository has one workaround for dropped
scheduled ticks and not two. The launcher half is textual on purpose: these files are the deployed
artefact, and reading them is cheaper than booting them.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.campaign_rearm import (  # noqa: E402
    BUSY_RUN_STATUSES,
    cooldown_seconds_for,
    decide_rearm,
    successor_inputs,
)

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
PAUSED = {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True}
IDLE_LONG_AGO = {"status": "completed", "updated_at": (NOW - timedelta(hours=3)).isoformat().replace("+00:00", "Z")}


def _decide(report=PAUSED, newest_run=IDLE_LONG_AGO, **overrides):
    kwargs = {"workflow_state": "active", "token_present": True, "now": NOW}
    kwargs.update(overrides)
    return decide_rearm(report, newest_run=newest_run, **kwargs)


def test_a_clean_wall_pause_hands_over_at_once_and_a_failure_pause_waits() -> None:
    """The covering CHAIN's rule: nothing is wrong with a leg that merely ran out of time."""
    assert cooldown_seconds_for("max_wall_seconds") == 0
    assert cooldown_seconds_for("provider_error") == 600 == cooldown_seconds_for("infrastructure_error")
    fresh = {"status": "completed", "updated_at": (NOW - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")}
    ok, reason = _decide(newest_run=fresh)
    assert ok, reason
    for report, wait in (({"status": "paused", "pause_reason": "provider_error", "resumable": True}, 300),
                         ({"status": "paused", "pause_reason": "provider_error", "resumable": True}, 700)):
        run = {"status": "completed", "updated_at": (NOW - timedelta(seconds=wait)).isoformat().replace("+00:00", "Z")}
        ok, reason = _decide(report, newest_run=run)
        assert ok is (wait >= 600), (wait, reason)


def test_chaining_stops_after_the_cap_and_a_human_dispatch_resets_it() -> None:
    ok, reason = _decide(chain_depth=39)
    assert ok, reason
    ok, reason = _decide(chain_depth=40)
    assert not ok and "reached the cap" in reason


def test_the_three_stops_a_human_uses_are_checked_before_anything_else() -> None:
    """Cancelled, regressed upload, terminal marker: each must beat a healthy-looking report."""
    ok, reason = _decide(was_cancelled=True)
    assert not ok and "cancelled" in reason
    ok, reason = _decide(stage_failed=True)
    assert not ok and "regressed" in reason
    ok, reason = _decide(report=PAUSED, newest_run=IDLE_LONG_AGO, marker_paths=["/nonexistent/wrapper_failed.json"])
    assert ok, reason  # an absent marker is not a stop
    ok, reason = _decide(marker_paths=[str(Path(__file__))])  # any existing file stands in for the marker
    assert not ok and "stopped on purpose" in reason


def test_only_a_resumable_pause_rearms_and_the_legs_own_flag_wins() -> None:
    for report, needle in (({"status": "completed", "pause_reason": None}, "'completed'"),
                           ({"status": "paused", "pause_reason": "infrastructure_error_retries_exhausted", "resumable": False}, "not resumable"),
                           ({"status": "paused", "pause_reason": "max_wall_seconds", "resumable": False}, "not resumable")):
        ok, reason = _decide(report)
        assert not ok and needle in reason, (report, reason)


def test_a_busy_group_is_not_stacked_onto() -> None:
    for status in sorted(BUSY_RUN_STATUSES):
        ok, reason = _decide(newest_run={"status": status, "updated_at": IDLE_LONG_AGO["updated_at"]})
        assert not ok and "already" in reason, (status, reason)


def test_an_unreadable_run_list_or_a_dead_workflow_refuses() -> None:
    """'Is a leg already running?' is the question the guard is built on; unknown is not 'no'."""
    ok, reason = _decide(newest_run=None)
    assert not ok and "blind" in reason
    ok, reason = _decide(workflow_state="disabled_manually")
    assert not ok and "disabled_manually" in reason
    ok, reason = _decide(token_present=False)
    assert not ok and "GITHUB_TOKEN" in reason


def test_the_payload_is_the_manual_click_and_nothing_more() -> None:
    """A chain may resume; it may not re-pin code or re-authorize billing."""
    inputs = successor_inputs("arena/x", 6)
    assert inputs == {"resume_previous": True, "chain_depth": "7", "ref": "arena/x"}
    assert "rebase_onto_ref" not in inputs and "execution_mode" not in inputs
    assert successor_inputs("", 0)["chain_depth"] == "1" and "ref" not in successor_inputs("", 0)


def _run_cli(tmp_path: Path, report: object, *args: str) -> subprocess.CompletedProcess:
    path = tmp_path / "campaign_report.json"
    path.write_text("{not json" if report is None else json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/campaign_rearm.py"), "--report", str(path),
         "--repo", "o/r", "--workflow", "w", "--api-url", "http://127.0.0.1:9", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
        env={"GITHUB_TOKEN": "test-token", "PATH": "/usr/bin:/bin"},
    )


def test_a_broken_rearm_never_reddens_a_leg(tmp_path: Path) -> None:
    """Every refusal - unreadable report, unroutable API - exits green and says why."""
    for report in (None, {}, PAUSED):
        proc = _run_cli(tmp_path, report)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "re-arm skipped" in proc.stdout, proc.stdout


LAUNCHERS = [
    ROOT / "handoff/mercury-pairwise-campaign.yml",
    ROOT / "handoff/reasoning-atria-pairwise-campaign.yml",
    ROOT / "docs/workflows/mercury-pairwise-campaign.yml.example",
    ROOT / "docs/workflows/reasoning-atria-pairwise-campaign.yml.example",
]


def _steps(path: Path) -> list[dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = raw["jobs"][list(raw["jobs"])[0]]
    return job["steps"]


def test_the_rearm_is_the_last_step_after_the_upload_and_skips_a_cancelled_leg() -> None:
    for path in LAUNCHERS:
        steps = _steps(path)
        step = steps[-1]
        assert step["name"].startswith("Re-arm the next leg"), f"{path.name}: {step['name']}"
        assert steps[-2]["name"].startswith("Upload"), f"{path.name}: rows must be uploaded before a successor is asked for"
        guard = step["if"]
        assert "always()" in guard and "!cancelled()" in guard and "steps.mode.outputs.mode != 'none'" in guard, (path.name, guard)
        assert "GITHUB_TOKEN" in step["env"], path.name


def test_the_chain_counter_is_a_declared_input_and_the_default_is_a_human_reset() -> None:
    for path in LAUNCHERS:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        inputs = (raw.get(True, raw.get("on")) or {})["workflow_dispatch"]["inputs"]
        assert inputs["chain_depth"]["default"] == "0", f"{path.name}: a human dispatch must reset the chain"
        assert inputs["resume_previous"]["default"] is True, f"{path.name}: resume_previous is the backstop if the payload is rejected"
        assert inputs["rebase_onto_ref"]["default"] == "", f"{path.name}: re-pinning code must stay opt-in"
        assert path.read_text(encoding="utf-8").count("actions: write") == 1, f"{path.name}: needs actions: write"


def test_every_flag_the_launcher_passes_exists_in_the_tool() -> None:
    """Mirrors tests/test_pairwise_matrix.py's flag check, for the tool this change adds."""
    source = (ROOT / "tools/campaign_rearm.py").read_text(encoding="utf-8")
    accepted = set(re.findall(r'add_argument\(\s*"--([a-z0-9-]+)"', source))
    assert {"report", "repo", "workflow", "api-url", "ref", "chain-depth", "max-chain-depth",
            "marker", "stage-failed", "cancelled", "min-interval-seconds", "dry-run"} <= accepted
    for path in LAUNCHERS:
        body = _steps(path)[-1]["run"]
        for flag in re.findall(r"(?<![\w-])--[a-z0-9-]+", body):
            assert flag.replace("--", "") in accepted, f"{path.name}: campaign_rearm.py does not accept {flag}"
        assert "--marker" in body and "--chain-depth" in body, f"{path.name}: the stops must be wired, not just available"


def test_handoff_and_docs_twins_stay_identical() -> None:
    for name in ("mercury-pairwise-campaign", "reasoning-atria-pairwise-campaign"):
        left = (ROOT / "handoff" / f"{name}.yml").read_bytes()
        right = (ROOT / "docs/workflows" / f"{name}.yml.example").read_bytes()
        assert left == right, f"{name}: the pasteable copy drifted from the documented one"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
