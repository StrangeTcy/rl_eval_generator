"""Tests for the leg that asks for its own successor.

The behaviour that matters here is the negative one: a campaign must never be able to spin the
scheduler, dispatch a second leg on top of a running one, redden its own leg because a
re-arm was refused, or widen what it is authorized to bill. Each test names the failure it
exists to block, and the launcher half is textual on purpose - these files are the deployed
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

from tools.campaign_rearm import BUSY_RUN_STATUSES, decide_rearm  # noqa: E402

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
PAUSED = {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True}
IDLE_LONG_AGO = {"status": "completed", "updated_at": (NOW - timedelta(hours=3)).isoformat().replace("+00:00", "Z")}


def _decide(report=PAUSED, newest_run=IDLE_LONG_AGO, **overrides):
    kwargs = {"min_interval_seconds": 1800, "workflow_state": "active", "token_present": True, "now": NOW}
    kwargs.update(overrides)
    return decide_rearm(report, newest_run=newest_run, **kwargs)


def test_a_completed_or_blocked_lineage_does_not_rearm() -> None:
    """The whole point of the pause rule: a finished or blocked campaign must not be restarted."""
    ok, reason = _decide({"status": "completed", "pause_reason": None})
    assert not ok and "'completed'" in reason
    ok, reason = _decide({"status": "paused", "pause_reason": "infrastructure_error_retries_exhausted", "resumable": False})
    assert not ok and "not resumable" in reason


def test_the_legs_own_resumable_verdict_beats_the_reason_table() -> None:
    """run_suite records resumability next to the pause; a stale reason string must not override it."""
    ok, reason = _decide({"status": "paused", "pause_reason": "max_wall_seconds", "resumable": False})
    assert not ok and "not resumable" in reason


def test_a_busy_group_is_not_piled_onto() -> None:
    for status in sorted(BUSY_RUN_STATUSES):
        ok, reason = _decide(newest_run={"status": status, "updated_at": IDLE_LONG_AGO["updated_at"]})
        assert not ok, (status, reason)
        assert "already" in reason


def test_a_recent_leg_is_not_re_dispatched() -> None:
    """The spin floor: a fast-failing leg cannot keep the scheduler busy."""
    recent = {"status": "completed", "updated_at": (NOW - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")}
    ok, reason = _decide(newest_run=recent)
    assert not ok and "spin" in reason
    ok, reason = _decide()
    assert ok and "idle for 180 min" in reason


def test_an_unreadable_run_list_refuses_to_dispatch_blind() -> None:
    """'Is a leg already running?' is the question the guard is built on; unknown is not 'no'."""
    ok, reason = _decide(newest_run=None)
    assert not ok and "blind" in reason


def test_a_disabled_workflow_is_reported_not_raced() -> None:
    ok, reason = _decide(workflow_state="disabled_manually")
    assert not ok and "disabled_manually" in reason
    ok, reason = _decide(token_present=False)
    assert not ok and "GITHUB_TOKEN" in reason


def _run_cli(tmp_path: Path, report: object, *args: str) -> subprocess.CompletedProcess:
    path = tmp_path / "campaign_report.json"
    if report is None:
        path.write_text("{not json", encoding="utf-8")
    else:
        path.write_text(json.dumps(report), encoding="utf-8")
    env = {"GITHUB_TOKEN": "token-for-the-test", "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/campaign_rearm.py"), "--report", str(path),
         "--repo", "o/r", "--workflow", "w", "--api-url", "http://127.0.0.1:9", *args],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=120,
    )


def test_a_corrupt_or_missing_report_exits_green(tmp_path: Path) -> None:
    """The step runs under `if: always()`; a leg that is already red must not get redder."""
    for report in (None, {}, {"status": "paused"}):
        proc = _run_cli(tmp_path, report)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "re-arm skipped" in proc.stdout, proc.stdout


def test_an_unreachable_api_cannot_redden_the_leg(tmp_path: Path) -> None:
    """Fail-open is the property; the cron remains the fallback, so a lost lookup costs a tick."""
    proc = _run_cli(tmp_path, PAUSED)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "re-arm skipped" in proc.stdout, proc.stdout
    assert "dispatch" not in proc.stdout.lower() or "skipped" in proc.stdout


LAUNCHERS = [
    ROOT / "handoff/mercury-pairwise-campaign.yml",
    ROOT / "handoff/reasoning-atria-pairwise-campaign.yml",
    ROOT / "docs/workflows/mercury-pairwise-campaign.yml.example",
    ROOT / "docs/workflows/reasoning-atria-pairwise-campaign.yml.example",
]


def _rearm_step(path: Path) -> tuple[dict, list[dict]]:
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    job = raw["jobs"][list(raw["jobs"])[0]]
    steps = job["steps"]
    step = next((s for s in steps if str(s.get("name", "")).startswith("Re-arm the next leg")), None)
    return step, steps


def test_the_rearm_runs_after_the_upload_and_only_on_a_working_leg() -> None:
    for path in LAUNCHERS:
        step, steps = _rearm_step(path)
        assert step is not None, f"{path.name}: no re-arm step"
        assert steps[-1]["name"] == step["name"], f"{path.name}: the re-arm must be the last step"
        guard = step["if"]
        assert "always()" in guard and "steps.mode.outputs.mode != 'none'" in guard, (path.name, guard)
        assert steps[-2]["name"].startswith("Upload"), f"{path.name}: rows must be uploaded before a successor is asked for"
        assert "GITHUB_TOKEN" in step["env"], path.name


def test_the_leg_may_ask_but_may_not_promote() -> None:
    for path in LAUNCHERS:
        step, _ = _rearm_step(path)
        assert path.read_text().count("actions: write") == 1, f"{path.name}: needs actions: write"
        body = step["run"]
        assert "rebase_onto_ref" not in body, f"{path.name}: a re-arm must never re-pin code"
        assert "execution_mode" not in body and "paid" not in body, f"{path.name}: a re-arm must not authorize billing"
        assert "exit 0" in body, f"{path.name}: a leg without a virtualenv must stay green"


def test_every_flag_the_launcher_passes_exists_in_the_tool() -> None:
    """Mirrors tests/test_pairwise_matrix.py's flag check, for the tool this change adds."""
    source = (ROOT / "tools/campaign_rearm.py").read_text(encoding="utf-8")
    accepted = set(re.findall(r'add_argument\(\s*"--([a-z0-9-]+)"', source))
    assert {"report", "repo", "workflow", "api-url", "ref", "min-interval-seconds", "dry-run"} <= accepted
    for path in LAUNCHERS:
        step, _ = _rearm_step(path)
        for flag in re.findall(r"(?<![\w-])--[a-z0-9-]+", step["run"]):
            assert flag.replace("--", "") in accepted, f"{path.name}: campaign_rearm.py does not accept {flag}"


def test_the_dispatch_relies_on_the_resume_default() -> None:
    """The payload sends resume_previous: true, but the launcher default is the backstop: if it
    ever read false, a re-arm would discard the paid T1 result and re-bill it."""
    for path in LAUNCHERS:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        inputs = (raw.get(True, raw.get("on")) or {})["workflow_dispatch"]["inputs"]
        assert inputs["resume_previous"]["default"] is True, f"{path.name}: resume_previous must default to true"
        assert inputs["rebase_onto_ref"]["default"] == "", f"{path.name}: rebase must stay opt-in"


def test_handoff_and_docs_twins_stay_identical() -> None:
    for name in ("mercury-pairwise-campaign", "reasoning-atria-pairwise-campaign"):
        left = (ROOT / "handoff" / f"{name}.yml").read_bytes()
        right = (ROOT / "docs/workflows" / f"{name}.yml.example").read_bytes()
        assert left == right, f"{name}: the pasteable copy drifted from the documented one"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
