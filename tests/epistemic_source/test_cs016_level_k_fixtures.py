"""CS016 E7 source-test behaviors adapted to the set-valued Level-k API.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 16 (lines 770-788).
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

bayesian_games = importlib.import_module("bayesian_games")
BayesianGame = bayesian_games.BayesianGame
is_best_response_everywhere = bayesian_games.is_best_response_everywhere
level_k_prediction = importlib.import_module("level_k").level_k_prediction
discriminating_instances = importlib.import_module(
    "experiments.instance_selection"
).discriminating_instances


def _hand_solved_dominant_action_game() -> BayesianGame:
    agents = ("A", "B")
    actions = dict.fromkeys(agents, ("left", "right"))

    def utility(type_profile, action_profile):
        del type_profile
        return {
            "A": Fraction(action_profile["A"] == "left"),
            "B": Fraction(action_profile["B"] == "right"),
        }

    return BayesianGame(
        agents=agents,
        types={"A": ("a0",), "B": ("b0",)},
        common_prior={("a0", "b0"): Fraction(1)},
        actions=actions,
        utility=utility,
    )


def test_hand_solved_level_two_prediction_reaches_the_unique_best_response_profile():
    game = _hand_solved_dominant_action_game()
    level0 = {"A": {"a0": "right"}, "B": {"b0": "left"}}
    expected = [{"A": {"a0": "left"}, "B": {"b0": "right"}}]

    assert level_k_prediction(game, level0, k=2) == expected
    assert all(is_best_response_everywhere(game, profile) for profile in expected)


def test_identical_wrong_predictors_are_not_flagged_as_correct_or_distinguished():
    game = _hand_solved_dominant_action_game()
    wrong_profile = {"A": {"a0": "right"}, "B": {"b0": "left"}}

    def wrong_a(_game):
        return wrong_profile

    def wrong_b(_game):
        return wrong_profile.copy()

    assert not is_best_response_everywhere(game, wrong_profile)
    assert discriminating_instances([game], wrong_a, wrong_b) == []
