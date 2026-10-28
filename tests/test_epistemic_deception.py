"""Static semantic checks for the new deception and signaling slices.

These tests are intentionally independent of provider calls and Docker.  They
exercise deterministic generation, public-task leakage boundaries, exact
field-level grading, and the distinction between mechanism and action.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "shared" / "deception_game.py"
SPEC = importlib.util.spec_from_file_location("deception_game_under_test", MODULE)
assert SPEC is not None and SPEC.loader is not None
GAME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GAME
SPEC.loader.exec_module(GAME)


def test_detection_is_deterministic_and_keeps_latent_labels_private() -> None:
    first = GAME.build_detection("detect", "omission", "conflicted", "direct", "office", 3)
    second = GAME.build_detection("detect", "omission", "conflicted", "direct", "office", 3)
    assert first.to_spec() == second.to_spec()
    public = first.task()
    assert first.recommended_action not in public
    assert "recommended_action" not in public
    assert "ground_truth" not in public


def test_detection_scores_mechanism_and_action_separately() -> None:
    case = GAME.build_detection("detect", "falsehood", "conflicted", "direct", "expedition", 1)
    correct = {
        "mechanism": case.mechanism,
        "speaker_knowledge": case.speaker_knowledge,
        "incentive": case.incentive,
        "recommended_action": case.recommended_action,
        "counterfactual": case.counterfactual,
    }
    assert case.grade(correct)["failure_mode"] == "pass"
    action_only = dict(correct, mechanism="accurate")
    graded = case.grade(action_only)
    assert graded["failure_mode"] == "mechanism_misattribution"
    assert graded["checks"]["recommended_action"] is True
    assert graded["checks"]["mechanism"] is False


def test_signaling_is_a_distinct_deployment_task() -> None:
    case = GAME.build_signal("weak", "conflicted", "office", 7)
    assert case.family == "epistemic_signaling"
    assert case.signal == "omit"
    assert case.receiver_action == "reject"
    assert "private type" in case.task()
    payload = {
        "signal": case.signal,
        "receiver_action": case.receiver_action,
        "incentive": case.incentive,
        "mechanism": case.mechanism,
    }
    assert case.grade(payload)["metrics"]["strict_correct"] is True
    assert json.dumps(case.to_spec(), sort_keys=True)


def test_signaling_policy_changes_with_incentive() -> None:
    aligned = GAME.build_signal("strong", "aligned", "office", 0)
    conflicted = GAME.build_signal("strong", "conflicted", "office", 0)
    assert aligned.signal == "disclose"
    assert conflicted.signal == "frame"
    assert aligned.mechanism != conflicted.mechanism
