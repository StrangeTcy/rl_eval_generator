"""The live-status reporter is refreshed from main, so a reporting fix stops needing a re-pin.

A campaign checks out a pinned ref, and the reporter is invoked from that checkout, so
the comment about a running campaign is rendered by whatever reporter the pin happened
to ship. On 2026-10-15 that produced a comment that was wrong in a way nobody could
see: `Updated` is the checkpoint's clock, and a leg that pauses in the Phase 2 READY
probe banks no row and writes no progress file, so Reasoning-Atria's comment sat frozen
at `2026-10-15T05:00:05Z` for about fifteen hours while six legs chained behind it.
Nothing in the body proved a reporter had run at all, so "nothing banked" and "the
reporter died" looked identical — and the Mercury campaign, whose legs did bank rows,
looked alive without being any more informative.

The fix has to reach campaigns that are mid-flight, and re-pinning a campaign is the one
action that can re-grade banked gate rows, so the reporter is fetched from main by the
workflow instead: `gh api .../contents/tools/campaign_status_sidecar.py?ref=main` is
written over the pinned checkout's copy immediately before the campaign step. The
reporter is not the measurement — it only renders the checkpoint — so this cannot move
the grading-code digest, which is computed from a `git archive` of the revision rather
than from the worktree. `--out`, `--pin-file`, the `tools/campaign_progress.py` the
sidecar imports and the interpreter all stay the pin's, which is what keeps the reported
state and the Issue number the pin's too.

Two files carry this, and neither can be pushed from a branch:
  * `handoff/paste/campaign_status_sidecar.py` — the reporter to paste onto main, at
    `tools/campaign_status_sidecar.py`, before the launchers below start reading it.
  * `handoff/paste/<launcher>.yml` — each pairwise launcher with the refresh step
    inserted. The automation token has no `workflows` permission, so these paths can
    only be changed by hand; the artifacts are the deployable bytes.

Order matters and is asserted here only as a comment, because it is a deployment
sequence rather than a property of these files: main's copy of the reporter is currently
**older** than the pins' (it lacks 66 lines the pins carry, including the
`infrastructure_unscored` handling that Mercury needs), so a launcher that reads from
main before the reporter lands there would downgrade the comment. Land the reporter
first; it is a no-op for the campaigns until a launcher reads it.
"""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PASTE = ROOT / "handoff" / "paste"
PAYLOAD = PASTE / "campaign_status_sidecar.py"
LAUNCHERS = (
    PASTE / "reasoning-atria-pairwise-campaign.yml",
    PASTE / "mercury-pairwise-campaign.yml",
)
REFRESH_STEP = "Refresh the live-status reporter from main"
CAMPAIGN_STEP = "Run T1 and pairwise campaign with live Issue status"
RENDER_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _steps(launcher: Path) -> list[dict[str, object]]:
    document = yaml.safe_load(launcher.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    jobs = document["jobs"]
    assert len(jobs) == 1, launcher.name
    steps = next(iter(jobs.values()))["steps"]
    assert isinstance(steps, list)
    return steps


def _step(launcher: Path, name: str) -> dict[str, object]:
    matches = [step for step in _steps(launcher) if step.get("name") == name]
    assert len(matches) == 1, (launcher.name, name, len(matches))
    return matches[0]


def _run(launcher: Path, name: str) -> str:
    run = _step(launcher, name)["run"]
    assert isinstance(run, str)
    return run


def test_both_pairwise_launchers_refresh_the_reporter_from_main() -> None:
    for launcher in LAUNCHERS:
        step = _step(launcher, REFRESH_STEP)
        assert step["continue-on-error"] is True, launcher.name
        assert "mode != 'none'" in str(step["if"]), launcher.name
        run = _run(launcher, REFRESH_STEP)
        assert "gh api" in run, launcher.name
        assert "contents/tools/campaign_status_sidecar.py" in run, launcher.name
        assert "${{ vars.CAMPAIGN_REPORTING_REF || 'main' }}" in run, launcher.name
        assert 'cp "$REPORTER" tools/campaign_status_sidecar.py' in run, launcher.name


def test_the_refresh_keeps_the_pins_copy_when_main_is_unusable() -> None:
    for launcher in LAUNCHERS:
        run = _run(launcher, REFRESH_STEP)
        # Nothing is installed unless all three checks pass: the download arrived, it is
        # not empty, and it compiles. A 404 body or an HTML error page fails the third.
        assert '&& [ -s "$REPORTER" ] && .venv/bin/python -m py_compile "$REPORTER"' in run, launcher.name
        installed, kept = run.split("else", 1)
        assert 'cp "$REPORTER"' in installed, launcher.name
        assert "cp " not in kept, launcher.name
        assert "stays the pin's copy" in kept, launcher.name


def test_the_refresh_runs_immediately_before_the_campaign_step() -> None:
    for launcher in LAUNCHERS:
        names = [step.get("name") for step in _steps(launcher)]
        assert names.index(REFRESH_STEP) == names.index(CAMPAIGN_STEP) - 1, launcher.name


def test_the_refresh_does_not_move_where_the_measurement_is_read() -> None:
    """The reporter moves; the state, the Issue pin and the interpreter do not."""
    for launcher in LAUNCHERS:
        run = _run(launcher, CAMPAIGN_STEP)
        assert run.count(".venv/bin/python tools/campaign_status_sidecar.py") == 2, launcher.name
        assert "reporting/" not in run, launcher.name
        assert "--out" in run and "--pin-file" in run, launcher.name
        assert "experiments/mercury_pairwise_status_issue.txt" in run or (
            "experiments/reasoning_atria_pairwise_status_issue.txt" in run
        ), launcher.name


def _load_payload() -> object:
    specification = importlib.util.spec_from_file_location("handoff_paste_reporter", PAYLOAD)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_the_payload_dates_the_comment_and_names_the_leg_that_rendered_it(monkeypatch) -> None:
    module = _load_payload()
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
    bare = module._rendered_by()
    assert RENDER_LINE.fullmatch(bare), bare
    monkeypatch.setenv("GITHUB_RUN_ID", "38758437040")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    named = module._rendered_by()
    assert "run 38758437040" in named and "attempt 1" in named, named


def test_the_heartbeat_sits_next_to_the_clock_that_was_lying() -> None:
    """The render line must follow `Updated`, because that is the line it corrects."""
    source = PAYLOAD.read_text(encoding="utf-8")
    updated = '- **Updated:**'
    rendered = '- **Comment rendered:**'
    assert source.count(rendered) >= 1
    lines = source.splitlines()
    index = next(i for i, line in enumerate(lines) if updated in line)
    assert rendered in lines[index + 1]
