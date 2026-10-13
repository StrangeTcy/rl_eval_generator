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

import inspect
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

try:
    from tools import campaign_rearm  # noqa: E402
    from tools.campaign_rearm import (  # noqa: E402
        BUSY_RUN_STATUSES,
        other_legs,
        cooldown_seconds_for,
        decide_rearm,
        successor_inputs,
    )
except ImportError as exc:  # pragma: no cover - the branch that runs on a tree without the tool
    # `tools/campaign_rearm.py` does not have to live on every branch: the launchers fetch it from the
    # ref they check out (`?ref=${{ github.sha }}`) and fall back to the checkout's copy when that fetch
    # comes up empty, so a host branch carrying only the workflow needs no copy of its own. main's copy
    # was deleted at 0b08e85 once it turned out to be an unparseable paste (SyntaxError at line 325),
    # and every leg's re-arm step had been exiting non-zero because of it. An import of a missing
    # module is a *collection* error though, which reddens the whole suite and hides the tests that did
    # fail for real - so this file opts out, by name, with the reason in its output.
    pytest.skip(f"no tools/campaign_rearm.py in this tree ({exc})", allow_module_level=True)

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
    """Every refusal - unreadable report, unroutable API - exits green and says why, loudly.

    Green is the point (a decline is not a fault), which is exactly why the decline also has to be an
    annotation: run 22 of the Mercury lineage ended 2026-10-12T23:59:53Z with a re-arm step that
    succeeded in 1 s and nobody knew it had said no until a human went looking.
    """
    for report in (None, {}, PAUSED):
        proc = _run_cli(tmp_path, report, "--sleep-cap", "0")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "re-arm skipped" in proc.stdout, proc.stdout
        assert "::warning::campaign re-arm declined:" in proc.stdout, proc.stdout


def test_handover_wait_is_the_seconds_sitting_out_buys_a_successor() -> None:
    """Pure arithmetic for the wait: how long, and when waiting cannot help."""
    from tools.campaign_rearm import handover_wait

    fresh = {"status": "completed",
             "updated_at": (NOW - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")}
    assert handover_wait(PAUSED, fresh, NOW) == 1190
    assert handover_wait(PAUSED, fresh, NOW, sleep_cap=600) == 0, "beyond the cap: nobody waits"
    assert handover_wait(PAUSED, fresh, NOW, sleep_cap=0) == 0, "waiting disabled"
    assert handover_wait(PAUSED, IDLE_LONG_AGO, NOW) == 0, "nothing to wait for"
    assert handover_wait({"status": "blocked", "pause_reason": "infrastructure_error",
                          "resumable": False}, fresh, NOW) == 0, "a blocked lineage never waits"
    assert handover_wait(PAUSED, {"status": "in_progress"}, NOW) == 0, "no readable timestamp"


def test_the_finished_leg_sits_out_the_window_then_asks(monkeypatch, tmp_path, capsys) -> None:
    """Refusing to dispatch inside the window used to mean never dispatching at all.

    Measured on the real thing: run 22 banked nothing for 2h22m, its report said `blocked`, and with
    `0e8cb71`'s floor any `paused` leg ending 3 s before the decision would have declined the same way
    - a chain that can only ever decline. This test runs main() with the sleep and the network pinned
    out and requires both halves of the behaviour: it waits, and then it asks.
    """
    from tools import campaign_rearm

    slept: list[float] = []
    fresh_run = {"status": "completed",
                 "updated_at": (datetime.now(timezone.utc) - timedelta(seconds=3))
                 .isoformat().replace("+00:00", "Z")}
    monkeypatch.setattr(campaign_rearm, "SLEEP", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(campaign_rearm, "find_workflow", lambda *a, **k: ({"id": 7, "state": "active"}, None))
    monkeypatch.setattr(campaign_rearm, "_request", lambda *a, **k: (200, {"workflow_runs": [fresh_run]}))
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    path = tmp_path / "campaign_report.json"
    path.write_text(json.dumps(PAUSED), encoding="utf-8")

    assert campaign_rearm.main(["--report", str(path), "--repo", "o/r", "--workflow", "w",
                                "--api-url", "https://api.invalid", "--sleep-cap", "1800",
                                "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert len(slept) == 1 and 1180 <= slept[0] <= 1200, (slept, out)
    assert "sitting it out" in out, out
    assert "would dispatch" in out, out


# Why the deployed path is not in this list: pushing a file under `.github/workflows/` is refused for
# this credential even on its own branch - measured, not assumed:
#   ! [remote rejected] arena/... (refusing to allow a GitHub App to create or update workflow
#   `.github/workflows/mercury-pairwise-campaign.yml` without `workflows` permission)
# So the branch owns the tool, the profile, the sidecar and the supervisor, and the workflow file owns
# only the two steps that read them. `main`'s launcher, and whatever a scheduled tick does, are out of
# reach from here by design.
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
            "marker", "stage-failed", "cancelled", "min-interval-seconds", "sleep-cap",
            "dry-run"} <= accepted
    for path in LAUNCHERS:
        body = _steps(path)[-1]["run"]
        # Only the tool invocation is a flag surface: the same step also calls `gh api --jq`, and
        # grading that as a campaign_rearm.py flag is how a guard starts failing on unrelated edits.
        body = body[body.index('.venv/bin/python "$REARM"'):]
        for flag in re.findall(r"(?<![\w-])--[a-z0-9-]+", body):
            assert flag.replace("--", "") in accepted, f"{path.name}: campaign_rearm.py does not accept {flag}"
        assert "--marker" in body and "--chain-depth" in body, f"{path.name}: the stops must be wired, not just available"


def test_the_rearm_runs_from_the_workflows_own_ref_not_the_pinned_checkout() -> None:
    """A handover that depends on the pinned tree is a handover that vanishes on old lineages.

    Atria run 15 (19:47:25 -> 2026-10-13T00:42:26Z) is the clean case that still did not continue: its
    report said `paused` / `max_wall_seconds` with 125 / 416 banked - exactly what the re-arm is for -
    and its job listing has no Re-arm step at all, because the definition it ran predates the paste.
    The mirror image of that, a new definition checking out an old pin, is answered here: the tool is
    fetched from the ref the workflow file came from, with the checkout as fallback and an annotation
    when neither has it.
    """
    for path in LAUNCHERS:
        step = _steps(path)[-1]
        body = step["run"]
        assert "contents/tools/campaign_rearm.py?ref=${{ github.sha }}" in body, path.name
        assert 'REARM="$RUNNER_TEMP/campaign_rearm.py"' in body, path.name
        assert '.venv/bin/python "$REARM"' in body, path.name
        assert 'cp tools/campaign_rearm.py "$REARM"' in body, f"{path.name}: the checkout copy is the fallback"
        assert "no compilable campaign_rearm.py" in body, f"{path.name}: a missing tool must be announced"
        assert "GH_TOKEN" in (step.get("env") or {}), f"{path.name}: the provider-free fetch needs a token"


def test_a_hand_click_can_clear_a_recorded_wrapper_stop_and_only_that(tmp_path: Path) -> None:
    """The lever that did not exist: two crashes in a row stop the campaign with no way to proceed.

    Mercury run 23 (2026-10-13T00:48:01Z) was refused by this guard - `operator stop: the carried state
    records a terminal failure (wrapper_exception); a rebase will not clear it` - and the refusal was
    correct by the campaign's own rule (tools/atria_campaign.py:1592-1596,
    tools/campaign_supervisor.py:207-215). But the operator was left holding a resume that refuses and a
    fresh dispatch that drops 190 banked episodes and re-bills T1, i.e. no lever at all. So the
    acknowledgement is a dispatch input: recorded on the run's own page, limited to a harness crash, and
    self-terminating because the new leg clears the marker at its start.
    """
    paid = '{"execution_mode": "paid"}'
    crash = {"pause_reason": "wrapper_exception", "detail": "RuntimeError: judge exited 1"}
    stop = "operator stop: wrapper_exception (wrapper recorded a terminal failure)"

    def decide(**kw):
        args = {"chain": "0", "event": "workflow_dispatch", "mode": "none", "reason": stop,
                "intent": paid, "clear": "true", "marker": crash}
        args.update(kw)
        return _run_bypass(tmp_path / f"case-{len(list(tmp_path.iterdir()))}", **args)

    got = decide()
    assert got["mode"] == "resume" and got["execution_mode"] == "paid", got
    assert "the wrapper-stop was lifted" in got["reason"], got
    assert stop in got["reason"], "the lifted refusal must still be quoted"

    for label, kw in (
        ("no acknowledgement", {"clear": "false"}),
        ("a spend ceiling is not liftable", {"marker": {"pause_reason": "max_api_calls"}}),
        ("exhausted retries are not liftable",
         {"marker": {"pause_reason": "infrastructure_error_retries_exhausted"}}),
        ("no marker file at all", {"marker": None}),
        ("a chained successor cannot self-authorise", {"chain": "2"}),
    ):
        got = decide(**kw)
        assert got["mode"] == "none", (label, got)

    # A cron tick never reaches the lift, however it is configured.
    assert decide(event="schedule", chain="")["mode"] == "none"


def test_the_wrapper_stop_is_declared_and_the_chain_never_carries_it() -> None:
    """The input exists, defaults to no, and is not part of a self-dispatched successor's payload."""
    for path in LAUNCHERS:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        inputs = (raw.get(True, raw.get("on")) or {})["workflow_dispatch"]["inputs"]
        assert inputs["clear_wrapper_stop"]["default"] is False, f"{path.name}: must default to no"
        assert inputs["clear_wrapper_stop"]["type"] == "boolean", path.name
        text = path.read_text(encoding="utf-8")
        assert text.count("clear_wrapper_stop") >= 3, f"{path.name}: declared and wired in both paths"
        assert "operator cleared a recorded wrapper stop" in text, f"{path.name}: the lift must be announced"
        for reason in ("wrapper_exception", "wrapper_transient_error", "infrastructure_error",
                       "docker_unavailable"):
            assert reason in text, (path.name, reason)
    assert "clear_wrapper_stop" not in successor_inputs("abc123", 3)


def test_every_copy_of_each_launcher_is_identical() -> None:
    """One byte stream, two paths: the handoff file and the documented example.

    A copy that lives in one place only is the point - the operator stopped hand-copying files, and a
    launcher edited in one location is how a main-side and a branch-side definition disagree for a day.
    The same accident already happened to `tools/campaign_rearm.py` on main (hand upload at e72ec43,
    identifiers replaced by emoji, syntactically invalid), which is what the re-arm step's compile gate
    is there to survive.
    """
    for name in ("mercury-pairwise-campaign", "reasoning-atria-pairwise-campaign"):
        texts = {
            "handoff": (ROOT / "handoff" / f"{name}.yml").read_bytes(),
            "example": (ROOT / "docs/workflows" / f"{name}.yml.example").read_bytes(),
        }
        assert texts["handoff"] == texts["example"], (
            name, {k: len(v.splitlines()) for k, v in texts.items()}
        )


def test_a_doomed_rebase_is_refused_before_it_costs_a_leg_and_a_terminal_marker() -> None:
    """The 3-minute death, caught at one API call instead.

    `tools/run_suite.py:294` keeps `manifest_commit` immutable in a resumed checkpoint and
    `--rebase-intent` waives only `gate_context_sha` (tools/atria_campaign.py:244), so rebasing a lineage
    that has an episode ledger raises inside the controller, exits 2, and writes the marker that then
    needs an operator acknowledgement. Mercury runs 22 and 24 (2026-10-12T23:59:57Z,
    2026-10-13T01:09:31Z) are that pair, both at 190 / 416.
    """
    for path in LAUNCHERS:
        body = [s for s in _steps(path) if str(s.get("name", "")).startswith("Decide")][0]["run"]
        assert "CARRIED_COMMIT=$(jq -r '.run.manifest_commit" in body, path.name
        assert 'TARGET_COMMIT=$(gh api "repos/${{ github.repository }}/commits/$REBASE"' in body, path.name
        start = body.index("CARRIED_COMMIT=")
        stop = body.index('if [ ! -s "$STATE_STAGE/campaign_intent.json" ]')
        preflight = body[start:stop]
        assert '"mode=none"' in preflight and preflight.index('"mode=none"') < preflight.index("exit 0"), path.name
        assert "rebase_onto_ref empty" in preflight, f"{path.name}: the refusal must name the fix"
        assert "campaign_intent.json" not in preflight, f"{path.name}: refuse before reading the intent"
        assert "run_suite.py:368" in preflight, f"{path.name}: cite the rule the rebase collides with"
        # The refusal has to yield to a target that can honour the move, or it blocks the way out.
        assert "contents/tools/run_suite.py?ref=$REBASE" in preflight, path.name
        assert preflight.index("grep -q allow_manifest_commit_rebase") < preflight.index('"mode=none"'), path.name


def test_the_rearm_refuses_to_execute_a_copy_that_does_not_compile() -> None:
    """A mangled upload must not be able to masquerade as a declined re-arm."""
    for path in LAUNCHERS:
        body = _steps(path)[-1]["run"]
        assert 'COMPILES=' in body and 'ast.parse' in body, path.name
        assert body.index("COMPILES=") < body.index('python -c "$COMPILES" "$REARM"'), path.name
        assert "does not compile; using the pinned checkout" in body, path.name
        assert "no compilable campaign_rearm.py" in body, path.name


def _bypass_block(path: Path, *, clear: str = "false") -> str:
    """The manual-dispatch bypass, extracted from the launcher that ships it.

    Not a re-typed copy: the block is sliced out of the step's own `run:` body, so this test grades
    the shell that will actually run on a runner, including its quoting.
    """
    body = [s for s in _steps(path) if str(s.get("name", "")).startswith("Decide")][0]["run"]
    start = body.index('CHAIN="${{ inputs.chain_depth }}"')
    stop = body.index('echo "mode=$MODE"', start)
    return body[start:stop].replace("${{ inputs.clear_wrapper_stop }}", clear)


def _run_bypass(tmp_path: Path, *, chain: str, event: str, mode: str, reason: str,
                intent: str | None, clear: str = "false",
                marker: dict | None = None) -> dict[str, str]:
    """Run the shipped bypass block under bash, with the launcher's own variable contract."""
    block = _bypass_block(LAUNCHERS[0], clear=clear).replace("${{ inputs.chain_depth }}", chain)
    # A fresh stage per call: intent=None must mean "the file is absent", not "whatever the previous
    # call in this test left behind".
    tmp_path.mkdir(parents=True, exist_ok=True)
    stage = tmp_path / f"state-{sum(1 for _ in tmp_path.iterdir())}"
    stage.mkdir(parents=True)
    if intent is not None:
        (stage / "campaign_intent.json").write_text(intent, encoding="utf-8")
    if marker is not None:
        (stage / "wrapper_failed.json").write_text(json.dumps(marker), encoding="utf-8")
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


def test_a_leg_arming_its_successor_is_not_an_other_leg() -> None:
    """The busy check has to ignore the leg doing the checking, or the chain can never self-continue.

    `runs?per_page=1` handed `decide_rearm` the *current* run - `in_progress`, because no step runs after
    its own job - so the answer was always "a leg is already in_progress", a leg that declines never arms
    the next one, and "it resumes automatically" meant "until a human files the next leg". Mercury run 28
    (38335486606) reached the tool at step 16 and still ended `campaign re-arm declined`.
    """
    self_run = {"id": 7, "status": "in_progress", "updated_at": NOW.isoformat().replace("+00:00", "Z")}
    busy = _decide(newest_run=self_run)
    assert busy[0] is False and "already in_progress" in busy[1], busy

    # Left out, the decision is taken on the previous leg - idle 3 h, which clears the floor.
    siblings = other_legs([self_run, IDLE_LONG_AGO], "7")
    assert siblings == [IDLE_LONG_AGO], siblings
    assert _decide(newest_run=siblings[0])[0] is True

    # A genuinely busy sibling still refuses: this exempts one run id, not the guard.
    queued_sibling = {"id": 8, "status": "queued", "updated_at": NOW.isoformat().replace("+00:00", "Z")}
    assert _decide(newest_run=other_legs([self_run, queued_sibling], "7")[0])[0] is False

    # With no run id to exclude - a local call - the list is untouched, strictness unchanged.
    assert other_legs([self_run], "") == [self_run]

    # And the shipped CLI really consults it, rather than this being a test of an unused helper.
    source = inspect.getsource(campaign_rearm.main)
    assert "args.exclude_run" in source and "per_page=20" in source, source
    assert "--exclude-run" in source or "exclude-run" in inspect.getsource(campaign_rearm)


def test_an_empty_run_list_is_idle_and_not_blindness() -> None:
    """The state a campaign's first leg is in, and the one that used to need a human.

    ``main`` asks the workflow for its runs, removes this leg from the answer (``other_legs``) and hands
    what is left to ``decide_rearm``. An empty remainder used to be read as "the run list could not be
    read", which is true of a 403 and equally true of a lineage whose runs have aged out of the listing -
    and answering either with a refusal means the second leg of a campaign can only ever arrive by hand.
    The distinction is now an argument, and the safe default (unreadable) is the one that refuses.
    """
    passed, reason = _decide(newest_run=None, run_list_readable=True)
    assert passed is True, reason
    assert "no other leg on record" in reason and "max_wall_seconds" in reason, reason

    # Unreadable stays refused, and so does the default: nothing is dispatched on an assumption.
    refused, why = _decide(newest_run=None)
    assert refused is False and "refusing to dispatch blind" in why, why

    # The exemption is for the age floor only. Everything a pause has to clear still has to clear.
    for kwargs in ({"workflow_state": "disabled_manually"}, {"token_present": False},
                   {"chain_depth": 40}, {"stage_failed": True}, {"was_cancelled": True}):
        blocked, why = _decide(newest_run=None, run_list_readable=True, **kwargs)
        assert blocked is False, (kwargs, why)

    # And a sibling that is genuinely busy arrives as a newest_run, so it still refuses.
    busy = {"id": 9, "status": "in_progress", "updated_at": NOW.isoformat().replace("+00:00", "Z")}
    assert _decide(newest_run=busy, run_list_readable=True)[0] is False

    # main threads the flag: readable listing -> True, and the flag is re-passed after the handover sleep.
    source = inspect.getsource(campaign_rearm.main)
    assert source.count("run_list_readable=run_list_readable") == 2, source
    assert "run_list_readable = status == 200" in source, source


def test_the_tool_survives_being_run_from_the_temp_directory_the_launcher_uses(tmp_path: Path) -> None:
    """The regression that stranded every campaign, asserted the way the launcher actually calls it.

    Step 16 fetches (or copies) this file to `$RUNNER_TEMP/campaign_rearm.py` and runs it *from there*, so
    the import that resolves inside a checkout does not resolve at all - and because the step is wrapped in
    `|| { echo "campaign re-arm declined: the tool exited non-zero"; }`, the crash was reported as a
    decision for every campaign that ever chained. The copy is placed in a directory with no `tools`
    package and no PYTHONPATH, run from that directory, and must exit 0 while still reading its report.
    """
    import os
    import shutil

    work = tmp_path / "runner_temp"
    work.mkdir()
    script = work / "campaign_rearm.py"
    shutil.copyfile(ROOT / "tools" / "campaign_rearm.py", script)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "GITHUB_TOKEN", "GH_TOKEN")}
    done = subprocess.run(
        [sys.executable, str(script), "--report", str(tmp_path / "absent.json"), "--dry-run"],
        cwd=str(work), capture_output=True, text=True, env=env,
    )
    assert done.returncode == 0, (done.returncode, done.stderr[-800:])
    assert "ModuleNotFoundError" not in done.stderr, done.stderr
    assert "campaign re-arm skipped: report unreadable" in done.stdout, done.stdout

    # The fallback constants are not allowed to drift from the module they stand in for.
    sys.path.insert(0, str(ROOT))
    from tools import campaign_rearm as in_tree
    from tools import campaign_supervisor as supervisor

    assert in_tree.RESUME_BACKOFF_SECONDS == supervisor.RESUME_BACKOFF_SECONDS
    assert in_tree.RESUMABLE_PAUSE_REASONS == supervisor.RESUMABLE_PAUSE_REASONS
