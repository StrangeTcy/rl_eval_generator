"""CS013 E6 fixtures for exhaustive finite pure-BNE enumeration.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 13 (lines 638-732).
"""

from __future__ import annotations

import copy
import importlib
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE_FILES = ROOT / "envs" / "epistemic_reasoning" / "files"
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))

task_engine = importlib.import_module("task_engine")
bayesian_games = importlib.import_module("bayesian_games")
BayesianGame = bayesian_games.BayesianGame
MAX_PURE_STRATEGY_PROFILES = bayesian_games.MAX_PURE_STRATEGY_PROFILES
enumerate_pure_bayesian_nash_equilibria = bayesian_games.enumerate_pure_bayesian_nash_equilibria
expected_utilities = bayesian_games.expected_utilities
is_best_response_everywhere = bayesian_games.is_best_response_everywhere
SpecError = importlib.import_module("event_bayes").SpecError


def _two_action_game(*, matching_pennies: bool) -> BayesianGame:
    agents = ("A", "B")
    types = {"A": ("a|private",), "B": ("b|private",)}
    actions = dict.fromkeys(agents, ("left", "right"))

    def utility(type_profile, action_profile):
        del type_profile
        matched = action_profile["A"] == action_profile["B"]
        if matching_pennies:
            return {"A": Fraction(matched), "B": Fraction(not matched)}
        return {agent: Fraction(matched) for agent in agents}

    return BayesianGame(
        agents=agents,
        types=types,
        common_prior={("a|private", "b|private"): Fraction(1)},
        actions=actions,
        utility=utility,
    )


def test_enumerator_returns_all_coordination_equilibria_and_empty_matching_pennies_set():
    coordination = _two_action_game(matching_pennies=False)
    equilibria = enumerate_pure_bayesian_nash_equilibria(coordination)
    assert len(equilibria) == 2
    assert all(is_best_response_everywhere(coordination, profile) for profile in equilibria)
    assert {
        tuple(equilibrium[agent][coordination.types[agent][0]] for agent in coordination.agents)
        for equilibrium in equilibria
    } == {("left", "left"), ("right", "right")}

    matching_pennies = _two_action_game(matching_pennies=True)
    assert enumerate_pure_bayesian_nash_equilibria(matching_pennies) == []


def test_conditional_utilities_use_ordered_type_tuples_and_exact_common_prior():
    agents = ("A", "B")
    a_types = ("north|west", "south")
    b_types = ("east", "west")
    common_prior = {
        ("north|west", "east"): Fraction(1, 3),
        ("north|west", "west"): Fraction(1, 6),
        ("south", "east"): Fraction(1, 6),
        ("south", "west"): Fraction(1, 3),
    }
    game = BayesianGame(
        agents=agents,
        types={"A": a_types, "B": b_types},
        common_prior=common_prior,
        actions={"A": ("red", "blue"), "B": ("red", "blue")},
        utility=lambda type_profile, action_profile: {
            "A": Fraction(
                action_profile["A"] == ("red" if type_profile["B"] == "east" else "blue")
            ),
            "B": Fraction(0),
        },
    )
    strategy = {
        "A": {"north|west": "red", "south": "blue"},
        "B": {"east": "red", "west": "blue"},
    }
    values = expected_utilities(game, "A", strategy, "north|west")
    assert values == {"red": Fraction(2, 3), "blue": Fraction(1, 3)}
    assert tuple(game.common_prior)[0] == ("north|west", "east")
    assert all(type(profile) is tuple for profile in game.common_prior)


def test_zero_marginal_declared_type_is_rejected_during_construction():
    with pytest.raises(SpecError, match="zero marginal prior"):
        BayesianGame(
            agents=("A",),
            types={"A": ("present", "impossible")},
            common_prior={("present",): Fraction(1)},
            actions={"A": ("x",)},
            utility=lambda type_profile, action_profile: {"A": Fraction(0)},
        )


def test_callable_receives_fresh_dictionaries_without_mutating_game_snapshots():
    def mutating_utility(type_profile, action_profile):
        assert type(type_profile) is dict
        assert type(action_profile) is dict
        type_profile["A"] = "changed"
        action_profile["A"] = "changed"
        return {"A": Fraction(7)}

    game = BayesianGame(
        agents=("A",),
        types={"A": ("only",)},
        common_prior={("only",): Fraction(1)},
        actions={"A": ("x",)},
        utility=mutating_utility,
    )
    first = game.utility({"A": "only"}, {"A": "x"})
    first["A"] = Fraction(99)
    assert game.types["A"] == ("only",)
    assert game.actions["A"] == ("x",)
    assert game.common_prior == {("only",): Fraction(1)}
    assert game.utility({"A": "only"}, {"A": "x"}) == {"A": Fraction(7)}


def test_unnormalized_common_prior_and_inexact_callable_payoffs_are_rejected():
    with pytest.raises(SpecError, match="sum exactly to one"):
        BayesianGame(
            agents=("A",),
            types={"A": ("only",)},
            common_prior={("only",): Fraction(1, 2)},
            actions={"A": ("x",)},
            utility=lambda type_profile, action_profile: {"A": Fraction(0)},
        )

    game = BayesianGame(
        agents=("A",),
        types={"A": ("only",)},
        common_prior={("only",): Fraction(1)},
        actions={"A": ("x",)},
        utility=lambda type_profile, action_profile: {"A": 0.5},
    )
    with pytest.raises(SpecError, match="exact int, string or Fraction"):
        game.utility({"A": "only"}, {"A": "x"})


def test_candidate_profile_limit_is_inclusive_and_checked_at_construction():
    at_limit = BayesianGame(
        agents=("A",),
        types={"A": ("only",)},
        common_prior={("only",): Fraction(1)},
        actions={"A": tuple(f"action_{index}" for index in range(MAX_PURE_STRATEGY_PROFILES))},
        utility=lambda type_profile, action_profile: {"A": Fraction(0)},
    )
    assert len(at_limit.actions["A"]) == MAX_PURE_STRATEGY_PROFILES

    with pytest.raises(SpecError, match="exceeds cap"):
        BayesianGame(
            agents=("A",),
            types={"A": ("t0", "t1")},
            common_prior={("t0",): Fraction(1, 2), ("t1",): Fraction(1, 2)},
            actions={"A": tuple(f"action_{index}" for index in range(142))},
            utility=lambda type_profile, action_profile: {"A": Fraction(0)},
        )


def test_serialized_game_uses_frozen_payoff_adapter_and_order_independent_answers():
    public = task_engine.build_instance("pure_bne", "expanded", 0)["public"]
    game = task_engine.bayesian_game_from_json(public)
    expected = task_engine.evaluate_public_task("pure_bne", public)
    assert all(type(profile) is tuple for profile in game.common_prior)
    assert all("|" in player_type for row in public["types"].values() for player_type in row)
    assert not task_engine.validate_answer("pure_bne", expected, public)

    reversed_answer = {"equilibria": list(reversed(expected["equilibria"]))}
    assert task_engine.answers_equal("pure_bne", reversed_answer, expected, public)
    if expected["equilibria"]:
        duplicate_answer = {"equilibria": [*expected["equilibria"], expected["equilibria"][0]]}
        assert task_engine.validate_answer("pure_bne", duplicate_answer, public)
        assert not task_engine.answers_equal("pure_bne", duplicate_answer, expected, public)

    original_public = copy.deepcopy(public)
    public["payoff_table"][0]["utilities"]["A"] = "99/1"
    public["common_prior"][0]["probability"] = "0/1"
    assert enumerate_pure_bayesian_nash_equilibria(game) == expected["equilibria"]

    malformed = copy.deepcopy(original_public)
    malformed["common_prior"][0]["type_profile"] = ["alpha|type_0|beta|type_0"]
    with pytest.raises(task_engine.TaskSpecError):
        task_engine.bayesian_game_from_json(malformed)


def test_generated_seeds_include_multiple_unique_and_empty_pure_equilibrium_sets():
    multiple = task_engine.build_instance("pure_bne", "compact", 0)
    unique = task_engine.build_instance("pure_bne", "compact", 1)
    empty = task_engine.build_instance("pure_bne", "compact", 2)
    assert len(multiple["expected_answer"]["equilibria"]) >= 2
    assert len(unique["expected_answer"]["equilibria"]) == 1
    assert empty["expected_answer"]["equilibria"] == []
    assert (
        len(task_engine.build_instance("pure_bne", "expanded", 2)["expected_answer"]["equilibria"])
        == 0
    )
