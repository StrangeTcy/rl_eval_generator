"""CS015 E7 implementation checks for explicit-anchor Level-k iteration.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 15 (lines 734-768).
CS016's separate source-test block is not counted as covered here.
"""

from __future__ import annotations

import importlib
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_FILES = ROOT / "envs" / "epistemic_reasoning" / "files"
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

bayesian_games = importlib.import_module("bayesian_games")
BayesianGame = bayesian_games.BayesianGame
SpecError = importlib.import_module("event_bayes").SpecError
level_k_prediction = importlib.import_module("level_k").level_k_prediction
discriminating_instances = importlib.import_module(
    "experiments.instance_selection"
).discriminating_instances


def _single_type_game(payoffs: dict[str, Fraction]) -> BayesianGame:
    actions = tuple(payoffs)
    return BayesianGame(
        agents=("A",),
        types={"A": ("t0",)},
        common_prior={("t0",): Fraction(1)},
        actions={"A": actions},
        utility=lambda type_profile, action_profile: {"A": payoffs[action_profile["A"]]},
    )


def test_level_zero_is_explicit_and_returned_as_a_fresh_profile():
    game = _single_type_game({"left": Fraction(0), "right": Fraction(1)})
    level0 = {"A": {"t0": "left"}}

    result = level_k_prediction(game, level0, k=0)

    assert result == [level0]
    assert result[0] is not level0
    assert result[0]["A"] is not level0["A"]
    level0["A"]["t0"] = "right"
    assert result == [{"A": {"t0": "left"}}]
    with pytest.raises(SpecError, match="nonnegative integer"):
        level_k_prediction(game, {"A": {"t0": "left"}}, k=-1)
    with pytest.raises(SpecError, match="nonnegative integer"):
        level_k_prediction(game, {"A": {"t0": "left"}}, k=True)


def test_exact_best_responses_and_all_ties_branch_through_later_levels():
    strict_game = _single_type_game({"left": Fraction(0), "right": Fraction(1)})
    anchor = {"A": {"t0": "left"}}
    assert level_k_prediction(strict_game, anchor, k=1) == [{"A": {"t0": "right"}}]

    tied_game = _single_type_game({"left": Fraction(1), "right": Fraction(1)})
    assert level_k_prediction(tied_game, anchor, k=1) == [
        {"A": {"t0": "left"}},
        {"A": {"t0": "right"}},
    ]
    assert level_k_prediction(tied_game, anchor, k=2) == [
        {"A": {"t0": "left"}},
        {"A": {"t0": "right"}},
    ]


def test_discriminator_only_selects_structural_disagreement():
    instances = ["same", "different"]
    selected = discriminating_instances(
        instances,
        predictor_a=lambda instance: instance,
        predictor_b=lambda instance: "same",
    )
    assert selected == ["different"]
