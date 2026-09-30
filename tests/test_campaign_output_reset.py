"""Regression tests for the destructive fresh-start inference.

Runs 36688365669 / 36720605647 / 36744995743 deleted a restored campaign
state artifact because the controller inferred "fresh start" from
GITHUB_EVENT_NAME alone, while the workflow's new self-dispatched
continuation resumed via workflow_dispatch. 73 banked episodes and ~12h of
gate rows were destroyed. These tests pin the contract that prevents it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.atria_campaign import _should_reset_output  # noqa: E402

PROFILE = {"provider": "atria"}


def _state(tmp_path: Path, episodes: int) -> Path:
    output = tmp_path / "atria_campaign"
    output.mkdir(parents=True, exist_ok=True)
    (output / "suite_checkpoint.json").write_text(
        json.dumps({"results": [{"case_id": f"case-{i}"} for i in range(episodes)]}),
        encoding="utf-8",
    )
    return output


def test_self_dispatched_resume_does_not_destroy_banked_episodes(tmp_path: Path) -> None:
    """The exact scenario that caused the loss."""
    output = _state(tmp_path, 73)

    reset, reason = _should_reset_output(
        output,
        explicit_fresh=False,
        profile=PROFILE,
        environ={"GITHUB_EVENT_NAME": "workflow_dispatch"},
    )

    assert reset is False
    assert "73 recorded episodes" in reason


def test_scheduled_resume_keeps_its_state(tmp_path: Path) -> None:
    output = _state(tmp_path, 73)

    reset, _ = _should_reset_output(
        output,
        explicit_fresh=False,
        profile=PROFILE,
        environ={"GITHUB_EVENT_NAME": "schedule"},
    )

    assert reset is False


def test_manual_continue_preserves_gate_only_state_without_overriding_event(tmp_path: Path) -> None:
    """A checked Continue runs the controller child with GITHUB_EVENT_NAME
    unset. This is essential before the first episode: a workflow_dispatch
    would otherwise infer freshness and discard banked gate rows.
    """
    output = _state(tmp_path, 0)
    (output / "instance_oracles_partial.json").write_text(
        json.dumps({"rows": {"gate-case": {"status": "passed"}}}), encoding="utf-8"
    )

    reset_as_dispatch, _ = _should_reset_output(
        output,
        explicit_fresh=False,
        profile=PROFILE,
        environ={"GITHUB_EVENT_NAME": "workflow_dispatch"},
    )
    reset_as_manual_resume, reason = _should_reset_output(
        output, explicit_fresh=False, profile=PROFILE, environ={}
    )

    assert reset_as_dispatch is True, "a raw workflow_dispatch is a fresh start with no episodes"
    assert reset_as_manual_resume is False, "the explicit Continue child must retain all gate rows"
    assert "local" in reason


def test_explicit_fresh_still_resets_even_with_progress(tmp_path: Path) -> None:
    """An operator may still discard a campaign deliberately."""
    output = _state(tmp_path, 73)

    reset, reason = _should_reset_output(
        output, explicit_fresh=True, profile=PROFILE, environ={}
    )

    assert reset is True
    assert "--fresh" in reason


def test_genuine_first_dispatch_still_clears_stale_rehearsal_output(tmp_path: Path) -> None:
    """The original purpose of the reset must survive: a real fresh start
    with no banked episodes still clears stale rehearsal artifacts."""
    output = _state(tmp_path, 0)

    reset, _ = _should_reset_output(
        output,
        explicit_fresh=False,
        profile=PROFILE,
        environ={"GITHUB_EVENT_NAME": "workflow_dispatch"},
    )

    assert reset is True


def test_missing_checkpoint_is_treated_as_no_progress(tmp_path: Path) -> None:
    output = tmp_path / "empty"
    output.mkdir()

    reset, _ = _should_reset_output(
        output,
        explicit_fresh=False,
        profile=PROFILE,
        environ={"GITHUB_EVENT_NAME": "workflow_dispatch"},
    )

    assert reset is True


def test_corrupt_checkpoint_does_not_crash_the_decision(tmp_path: Path) -> None:
    output = tmp_path / "corrupt"
    output.mkdir()
    (output / "suite_checkpoint.json").write_text("NOT JSON", encoding="utf-8")

    reset, _ = _should_reset_output(
        output,
        explicit_fresh=False,
        profile=PROFILE,
        environ={"GITHUB_EVENT_NAME": "workflow_dispatch"},
    )

    assert reset is True
