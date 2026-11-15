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
    assert "ground_truth" not in public
    accurate = GAME.build_detection("detect", "accurate", "conflicted", "partial", "office", 3)
    falsehood = GAME.build_detection("detect", "falsehood", "conflicted", "partial", "office", 3)
    assert accurate.hidden_fact != falsehood.hidden_fact
    assert accurate.observable_evidence == falsehood.observable_evidence
    assert accurate.task() == falsehood.task()
    assert accurate.recommended_action == falsehood.recommended_action == "verify"
    assert accurate.counterfactual == falsehood.counterfactual == "audit_undetermined"


def test_detection_scores_mechanism_and_action_separately() -> None:
    case = GAME.build_detection("detect", "falsehood", "conflicted", "direct", "expedition", 1)
    correct = {
        "mechanism": case.mechanism,
        "speaker_knowledge": case.speaker_knowledge,
        "incentive": case.incentive,
        "recommended_action": case.recommended_action,
        "counterfactual": case.counterfactual,
        "justification": "The observed final record contradicts the informed report under conflicted incentives.",
    }
    assert case.grade(correct)["failure_mode"] == "pass"
    action_only = dict(correct, mechanism="accurate")
    graded = case.grade(action_only)
    assert graded["failure_mode"] == "mechanism_misattribution"
    assert graded["checks"]["recommended_action"] is True
    assert graded["checks"]["mechanism"] is False
    missing = correct.copy()
    missing.pop("justification")
    assert case.grade(missing)["metrics"]["score"] == 0.0
    extra = correct.copy()
    extra["unrecognized"] = "extra field"
    assert case.grade(extra)["metrics"]["score"] == 0.0
    invalid = correct.copy()
    invalid["justification"] = " "
    assert case.grade(invalid)["metrics"]["score"] == 0.0
    invalid["justification"] = "x" * 601
    assert case.grade(invalid)["metrics"]["score"] == 0.0
    invalid["justification"] = None
    assert case.grade(invalid)["metrics"]["score"] == 0.0
    accurate = GAME.build_detection("counterfactual", "accurate", "conflicted", "partial", "expedition", 1)
    falsehood = GAME.build_detection("counterfactual", "falsehood", "conflicted", "partial", "expedition", 1)
    uncertain = correct.copy()
    uncertain["mechanism"] = "underdetermined"
    uncertain["recommended_action"] = "verify"
    uncertain["counterfactual"] = "audit_undetermined"
    uncertain["justification"] = "The redacted final record leaves accurate reporting and falsehood observationally equivalent."
    assert accurate.grade(uncertain)["failure_mode"] == "pass"
    assert falsehood.grade(uncertain)["failure_mode"] == "pass"
    certain = uncertain.copy()
    certain["mechanism"] = "accurate"
    assert accurate.grade(certain)["failure_mode"] == "mechanism_misattribution"
    aligned = GAME.build_detection("detect", "accurate", "aligned", "partial", "office", 3)
    assert aligned.counterfactual == "audit_unchanged"


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
        "justification": "The weak/conflicted policy cell prescribes omit and reject.",
    }
    assert case.grade(payload)["metrics"]["strict_correct"] is True
    assert json.dumps(case.to_spec(), sort_keys=True)


def test_signaling_policy_changes_with_incentive() -> None:
    aligned = GAME.build_signal("strong", "aligned", "office", 0)
    conflicted = GAME.build_signal("strong", "conflicted", "office", 0)
    assert aligned.signal == "disclose"
    assert conflicted.signal == "frame"
    assert aligned.mechanism != conflicted.mechanism
