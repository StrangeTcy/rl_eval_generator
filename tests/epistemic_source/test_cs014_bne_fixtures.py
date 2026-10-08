"""CS014 E6 regression fixtures for multiple equilibria and prior validation.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 14 (lines 709-730).
This is a distinct tests-only block; no semantic implementation is added here.
"""

from __future__ import annotations

import importlib
import itertools
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_FILES = ROOT / "envs" / "epistemic_reasoning" / "files"
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))

bayesian_games = importlib.import_module("bayesian_games")
BayesianGame = bayesian_games.BayesianGame
enumerate_pure_bayesian_nash_equilibria = bayesian_games.enumerate_pure_bayesian_nash_equilibria
is_best_response_everywhere = bayesian_games.is_best_response_everywhere
SpecError = importlib.import_module("event_bayes").SpecError


def test_coordination_fixture_enumerates_multiple_profile_equilibria():
    agents = ("A", "B", "C")
    types = {
        "A": ("a0", "a1"),
        "B": ("b0", "b1"),
        "C": ("c0", "c1"),
    }
    actions = dict.fromkeys(agents, ("red", "blue"))
    type_profiles = itertools.product(*(types[agent] for agent in agents))
    common_prior = {profile: Fraction(1, 8) for profile in type_profiles}

    def utility(type_profile, action_profile):
        del type_profile
        shared_choice = len(set(action_profile.values())) == 1
        return {agent: Fraction(shared_choice) for agent in agents}

    game = BayesianGame(
        agents=agents,
        types=types,
        common_prior=common_prior,
        actions=actions,
        utility=utility,
    )
    equilibria = enumerate_pure_bayesian_nash_equilibria(game)

    assert len(equilibria) >= 2
    assert all(is_best_response_everywhere(game, profile) for profile in equilibria)
    assert any(
        all(
            equilibrium[agent][player_type] == "red"
            for agent in agents
            for player_type in types[agent]
        )
        for equilibrium in equilibria
    )
    assert any(
        all(
            equilibrium[agent][player_type] == "blue"
            for agent in agents
            for player_type in types[agent]
        )
        for equilibrium in equilibria
    )


def test_nonunit_common_prior_is_rejected_during_game_construction():
    with pytest.raises(SpecError, match="sum exactly to one"):
        BayesianGame(
            agents=("A", "B"),
            types={"A": ("a0", "a1"), "B": ("b0", "b1")},
            common_prior={
                ("a0", "b0"): Fraction(1, 4),
                ("a1", "b1"): Fraction(1, 4),
            },
            actions={"A": ("x",), "B": ("x",)},
            utility=lambda type_profile, action_profile: {
                "A": Fraction(0),
                "B": Fraction(0),
            },
        )
