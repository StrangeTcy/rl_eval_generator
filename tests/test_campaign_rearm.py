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


def test_the_floor_never_undercuts_the_supervisors_own_resume_backoff() -> None:
    """The bug this test exists for: chaining into a leg that would refuse.

    ``campaign_supervisor.decide_tick`` answers ``mode="none"`` to any resume younger than
    ``RESUME_BACKOFF_SECONDS`` (tools/campaign_supervisor.py:285-292), and that refused leg does not
    re-arm either - so a re-arm that dispatches inside the window does not resume sooner, it ends
    the chain. The re-arm must therefore never ask earlier than the backoff, for any reason.
    """
    from tools.campaign_rearm import effective_floor_seconds
    from tools.campaign_supervisor import RESUMABLE_PAUSE_REASONS, RESUME_BACKOFF_SECONDS

    assert effective_floor_seconds("max_wall_seconds") == RESUME_BACKOFF_SECONDS == 1200
    assert effective_floor_seconds("provider_error") == 1200
    for reason in sorted(RESUMABLE_PAUSE_REASONS):
        assert effective_floor_seconds(reason, 0) >= RESUME_BACKOFF_SECONDS, reason
        assert effective_floor_seconds(reason, 99_999) == 99_999, reason

    fresh = {"status": "completed", "updated_at": (NOW - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")}
    ok, reason = _decide(newest_run=fresh)
    assert not ok and "mode=none" in reason, reason
    inside = {"status": "completed", "updated_at": (NOW - timedelta(seconds=1199)).isoformat().replace("+00:00", "Z")}
    assert not _decide(newest_run=inside)[0]
    outside = {"status": "completed", "updated_at": (NOW - timedelta(seconds=1201)).isoformat().replace("+00:00", "Z")}
    assert _decide(newest_run=outside)[0], _decide(newest_run=outside)[1]


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


def _bypass_block(path: Path) -> str:
    """The manual-dispatch bypass, extracted from the launcher that ships it.

    Not a re-typed copy: the block is sliced out of the step's own `run:` body, so this test grades
    the shell that will actually run on a runner, including its quoting.
    """
    body = [s for s in _steps(path) if str(s.get("name", "")).startswith("Decide")][0]["run"]
    start = body.index('CHAIN="${{ inputs.chain_depth }}"')
    stop = body.index('echo "mode=$MODE"', start)
    return body[start:stop]


def _run_bypass(tmp_path: Path, *, chain: str, event: str, mode: str, reason: str,
                intent: str | None) -> dict[str, str]:
    """Run the shipped bypass block under bash, with the launcher's own variable contract."""
    block = _bypass_block(LAUNCHERS[0]).replace("${{ inputs.chain_depth }}", chain)
    # A fresh stage per call: intent=None must mean "the file is absent", not "whatever the previous
    # call in this test left behind".
    stage = tmp_path / f"state-{sum(1 for _ in tmp_path.iterdir())}"
    stage.mkdir(parents=True)
    if intent is not None:
        (stage / "campaign_intent.json").write_text(intent, encoding="utf-8")
    script = tmp_path / "bypass.sh"
    script.write_text("\n".join([
        "set -uo pipefail",
        f'GITHUB_EVENT_NAME="{event}"',
        f'MODE="{mode}"',
        f'REASON="{reason}"',
        'REF=""',
        'PINNED_REF="abc123def"',
        f'STATE_STAGE="{stage}"',
        block,
        'printf "%s|%s|%s|%s\n" "${MODE:-}" "${REF:-}" "${EXECUTION_MODE:-}" "${REASON:-}"',
    ]) + "\n", encoding="utf-8")
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    got, _, tail = proc.stdout.strip().partition("|")
    ref, _, rest = tail.partition("|")
    execution_mode, _, why = rest.partition("|")
    return {"mode": got, "ref": ref, "execution_mode": execution_mode, "reason": why}


def test_a_human_click_starts_the_leg_instead_of_counting_down(tmp_path: Path) -> None:
    """The behaviour the operator asked for in one sentence, and the limits on it.

    Measured cause: Mercury run 21 (2026-10-12T21:27:51Z) was a manual `workflow_dispatch` 49 s after
    a pause and its only output was the annotation `this leg declined to continue the campaign:
    backoff: paused 49s ago, retry in 1150s`. `decide_tick` applies RESUME_BACKOFF_SECONDS to every
    resume and takes no bypass flag, so the exemption had to live in the step that calls it.
    """
    for path in LAUNCHERS:
        assert "HUMAN_CLICK" in path.read_text(encoding="utf-8"), f"{path.name}: no manual bypass"

    paid = '{"execution_mode": "paid"}'
    got = _run_bypass(tmp_path, chain="0", event="workflow_dispatch", mode="none",
                      reason="backoff: paused 49s ago, retry in 1150s", intent=paid)
    assert got["mode"] == "resume" and got["ref"] == "abc123def" and got["execution_mode"] == "paid", got
    assert "backoff: paused 49s ago" in got["reason"], "the lifted refusal must still be quoted"

    # A chained successor is a workflow_dispatch too, and it must keep waiting: an immediate
    # re-dispatch inside the window is what re-creates the tight loop the window exists to stop.
    for chain in ("1", "39"):
        got = _run_bypass(tmp_path, chain=chain, event="workflow_dispatch", mode="none",
                          reason="backoff: paused 49s ago, retry in 1150s", intent=paid)
        assert got["mode"] == "none" and got["reason"].startswith("backoff:"), (chain, got)

    # A click cannot clear an objection that is not the window.
    for reason in ("operator pause: max_api_calls", "no Mercury pairwise state artifact",
                   "ceiling override is not above the spent value"):
        got = _run_bypass(tmp_path, chain="0", event="workflow_dispatch", mode="none",
                          reason=reason, intent=paid)
        assert got["mode"] == "none", (reason, got)

    # A cron tick is not a click, whatever its inputs look like.
    got = _run_bypass(tmp_path, chain="", event="schedule", mode="none",
                      reason="backoff: paused 49s ago, retry in 1150s", intent=paid)
    assert got["mode"] == "none", got

    # Billing authority is read back from the carried intent, never from the form: no readable
    # intent, no resume - and the reason says who tried.
    for intent in (None, "{}", '{"execution_mode": "paid-ish"}', '{"execution_mode": "gates_only"}'):
        got = _run_bypass(tmp_path, chain="0", event="workflow_dispatch", mode="none",
                          reason="backoff: paused 49s ago", intent=intent)
        if intent == '{"execution_mode": "gates_only"}':
            assert got["mode"] == "resume" and got["execution_mode"] == "gates_only", got
        else:
            assert got["mode"] == "none" and "no readable execution mode" in got["reason"], (intent, got)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
