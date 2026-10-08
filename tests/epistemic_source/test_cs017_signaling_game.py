"""CS017 E8 implementation checks for exact pure PBE assessments.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 17 (lines 792-839).
CS018's source-test fixtures remain a separate, unprocessed block.
"""

from __future__ import annotations

import importlib
import sys
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_FILES = ROOT / "envs" / "epistemic_reasoning" / "files"
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))

signaling = importlib.import_module("signaling_game")
PBEAssessment = signaling.PBEAssessment
SignalingGame = signaling.SignalingGame
enumerate_pbe = signaling.enumerate_pbe
is_perfect_bayesian_equilibrium = signaling.is_perfect_bayesian_equilibrium
receiver_best_response = signaling.receiver_best_response
receiver_belief = signaling.receiver_belief
SpecError = importlib.import_module("event_bayes").SpecError


def _separating_game() -> SignalingGame:
    types = ("t1", "t2")
    messages = ("m1", "m2")
    return SignalingGame(
        types=types,
        prior={"t1": Fraction(1, 3), "t2": Fraction(2, 3)},
        messages=messages,
        receiver_actions=("accept", "reject"),
        sender_utility=lambda player_type, message, action: Fraction(0),
        receiver_utility=lambda player_type, message, action: Fraction(
            action == ("accept" if message == "m1" else "reject")
        ),
        off_path_beliefs={
            "m1": {"t1": Fraction(1), "t2": Fraction(0)},
            "m2": {"t1": Fraction(0), "t2": Fraction(1)},
        },
    )


def test_separating_strategy_produces_exact_on_path_posteriors():
    game = _separating_game()
    sender_strategy = {"t1": "m1", "t2": "m2"}

    assert receiver_belief(game, sender_strategy, "m1") == {
        "t1": Fraction(1),
        "t2": Fraction(0),
    }
    assert receiver_belief(game, sender_strategy, "m2") == {
        "t1": Fraction(0),
        "t2": Fraction(1),
    }


def test_receiver_response_uses_the_actual_message_and_keeps_exact_ties():
    game = _separating_game()
    prior = {"t1": Fraction(1, 3), "t2": Fraction(2, 3)}

    assert receiver_best_response(game, prior, "m1") == ("accept",)
    assert receiver_best_response(game, prior, "m2") == ("reject",)

    tied_game = SignalingGame(
        types=("t",),
        prior={"t": Fraction(1)},
        messages=("m",),
        receiver_actions=("first", "second"),
        sender_utility=lambda player_type, message, action: Fraction(0),
        receiver_utility=lambda player_type, message, action: Fraction(0),
        off_path_beliefs={"m": {"t": Fraction(1)}},
    )
    assert receiver_best_response(tied_game, {"t": Fraction(1)}, "m") == (
        "first",
        "second",
    )


def test_enumerator_returns_immutable_complete_pure_assessments():
    game = SignalingGame(
        types=("t",),
        prior={"t": Fraction(1)},
        messages=("m",),
        receiver_actions=("left", "right"),
        sender_utility=lambda player_type, message, action: Fraction(0),
        receiver_utility=lambda player_type, message, action: Fraction(0),
        off_path_beliefs={"m": {"t": Fraction(1)}},
    )

    assessments = enumerate_pbe(game)

    assert len(assessments) == 2
    assert all(isinstance(assessment, PBEAssessment) for assessment in assessments)
    assert [assessment.receiver_strategy["m"] for assessment in assessments] == [
        "left",
        "right",
    ]
    assert all(assessment.beliefs["m"] == {"t": Fraction(1)} for assessment in assessments)
    assert all(
        is_perfect_bayesian_equilibrium(
            game, assessment.sender_strategy, assessment.receiver_strategy
        )
        for assessment in assessments
    )
    assert isinstance(assessments[0].sender_strategy, MappingProxyType)
    with pytest.raises(TypeError):
        assessments[0].receiver_strategy["m"] = "left"


def test_game_snapshots_probability_inputs_and_rejects_inexact_utility():
    prior = {"t1": Fraction(1, 3), "t2": Fraction(2, 3)}
    off_path_beliefs = {
        "m1": {"t1": Fraction(1), "t2": Fraction(0)},
        "m2": {"t1": Fraction(0), "t2": Fraction(1)},
    }
    game = SignalingGame(
        types=("t1", "t2"),
        prior=prior,
        messages=("m1", "m2"),
        receiver_actions=("a",),
        sender_utility=lambda player_type, message, action: Fraction(0),
        receiver_utility=lambda player_type, message, action: Fraction(0),
        off_path_beliefs=off_path_beliefs,
    )
    prior["t1"] = Fraction(1)
    off_path_beliefs["m1"]["t1"] = Fraction(0)
    assert game.prior == {"t1": Fraction(1, 3), "t2": Fraction(2, 3)}
    assert game.off_path_beliefs["m1"] == {"t1": Fraction(1), "t2": Fraction(0)}

    inexact_game = SignalingGame(
        types=("t",),
        prior={"t": Fraction(1)},
        messages=("m",),
        receiver_actions=("a",),
        sender_utility=lambda player_type, message, action: 0.5,
        receiver_utility=lambda player_type, message, action: Fraction(0),
        off_path_beliefs={"m": {"t": Fraction(1)}},
    )
    with pytest.raises(SpecError, match="exact int, string or Fraction"):
        enumerate_pbe(inexact_game)


def test_declared_types_need_positive_prior_mass_and_search_respects_cap():
    with pytest.raises(SpecError, match="positive prior mass"):
        SignalingGame(
            types=("positive", "zero"),
            prior={"positive": Fraction(1), "zero": Fraction(0)},
            messages=("m",),
            receiver_actions=("a",),
            sender_utility=lambda player_type, message, action: Fraction(0),
            receiver_utility=lambda player_type, message, action: Fraction(0),
            off_path_beliefs={"m": {"positive": Fraction(1), "zero": Fraction(0)}},
        )

    many_types = tuple(f"t{index}" for index in range(14))
    with pytest.raises(SpecError, match="candidate count.*exceeds cap 20000"):
        SignalingGame(
            types=many_types,
            prior={},
            messages=("m0", "m1"),
            receiver_actions=("a0", "a1"),
            sender_utility=lambda player_type, message, action: Fraction(0),
            receiver_utility=lambda player_type, message, action: Fraction(0),
            off_path_beliefs={},
        )
