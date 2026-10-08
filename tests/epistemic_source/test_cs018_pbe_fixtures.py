"""CS018 E8 source-test behaviors for sender incentives and off-path beliefs.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 18 (lines 841-864).
This is a distinct tests-only block; no semantic implementation is added here.
"""

from __future__ import annotations

import importlib
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_FILES = ROOT / "envs" / "epistemic_reasoning" / "files"
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))

signaling = importlib.import_module("signaling_game")
SignalingGame = signaling.SignalingGame
enumerate_pbe = signaling.enumerate_pbe
is_perfect_bayesian_equilibrium = signaling.is_perfect_bayesian_equilibrium
receiver_best_response = signaling.receiver_best_response
receiver_belief = signaling.receiver_belief


def test_local_receiver_best_responses_do_not_hide_sender_deviations():
    game = SignalingGame(
        types=("t1", "t2"),
        prior={"t1": Fraction(1, 2), "t2": Fraction(1, 2)},
        messages=("m1", "m2"),
        receiver_actions=("x", "y"),
        sender_utility=lambda player_type, message, action: Fraction(
            2 if player_type == "t1" and message == "m2" else int(message == "m2")
        ),
        receiver_utility=lambda player_type, message, action: Fraction(
            int(action == ("x" if message == "m1" else "y"))
        ),
        off_path_beliefs={
            "m1": {"t1": Fraction(1), "t2": Fraction(0)},
            "m2": {"t1": Fraction(0), "t2": Fraction(1)},
        },
    )
    sender_strategy = {"t1": "m1", "t2": "m2"}
    receiver_strategy = {"m1": "x", "m2": "y"}

    for message in game.messages:
        belief = receiver_belief(game, sender_strategy, message)
        assert receiver_strategy[message] in receiver_best_response(game, belief, message)
    assert not is_perfect_bayesian_equilibrium(game, sender_strategy, receiver_strategy)
    assessments = enumerate_pbe(game)
    assert all(assessment.sender_strategy != sender_strategy for assessment in assessments)
    assert any(assessment.sender_strategy == {"t1": "m2", "t2": "m2"} for assessment in assessments)


def test_zero_evidence_message_uses_explicit_off_path_belief():
    game = SignalingGame(
        types=("t1", "t2"),
        prior={"t1": Fraction(1, 3), "t2": Fraction(2, 3)},
        messages=("m_pool", "m_off"),
        receiver_actions=("a",),
        sender_utility=lambda player_type, message, action: Fraction(0),
        receiver_utility=lambda player_type, message, action: Fraction(0),
        off_path_beliefs={
            "m_pool": {"t1": Fraction(1, 3), "t2": Fraction(2, 3)},
            "m_off": {"t1": Fraction(1), "t2": Fraction(0)},
        },
    )
    pooling_strategy = {"t1": "m_pool", "t2": "m_pool"}

    assert receiver_belief(game, pooling_strategy, "m_off") == {
        "t1": Fraction(1),
        "t2": Fraction(0),
    }
