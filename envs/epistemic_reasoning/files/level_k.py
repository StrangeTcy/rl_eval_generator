"""Descriptive finite Level-k iteration from an explicit pure-strategy anchor.

This module computes conditional iterated best responses; it does not define a
normative ground truth, choose a Level-0 model, or add a scored task variant.
Exact ties are set-valued and all resulting joint strategies continue to the
next synchronous level.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import product

from bayesian_games import (
    MAX_PURE_STRATEGY_PROFILES,
    BayesianGame,
    expected_utilities,
    pure_strategy_profile_count,
)
from event_bayes import SpecError

Strategy = dict[str, dict[str, str]]
StrategySignature = tuple[tuple[str, tuple[str, ...]], ...]


def _normalize_strategy(game: BayesianGame, strategy: object) -> Strategy:
    if not isinstance(strategy, Mapping) or set(strategy) != set(game.agents):
        raise SpecError("level0 must define exactly the declared agents")
    normalized: Strategy = {}
    for agent in game.agents:
        rows = strategy[agent]
        if not isinstance(rows, Mapping) or set(rows) != set(game.types[agent]):
            raise SpecError(f"level0 must define exactly every type of {agent}")
        copied = dict(rows)
        if any(
            type(action) is not str or action not in game.actions[agent]
            for action in copied.values()
        ):
            raise SpecError(f"level0 for {agent} uses an undeclared action")
        normalized[agent] = {player_type: copied[player_type] for player_type in game.types[agent]}
    return normalized


def _signature(game: BayesianGame, strategy: Strategy) -> StrategySignature:
    return tuple(
        (agent, tuple(strategy[agent][player_type] for player_type in game.types[agent]))
        for agent in game.agents
    )


def _best_response_profiles(game: BayesianGame, previous: Strategy) -> list[Strategy]:
    coordinates: list[tuple[str, str]] = []
    action_choices: list[tuple[str, ...]] = []
    for agent in game.agents:
        for player_type in game.types[agent]:
            utilities = expected_utilities(game, agent, previous, player_type)
            best_value = max(utilities.values())
            best_actions = tuple(
                action for action in game.actions[agent] if utilities[action] == best_value
            )
            coordinates.append((agent, player_type))
            action_choices.append(best_actions)

    successors: dict[StrategySignature, Strategy] = {}
    for selected_actions in product(*action_choices):
        strategy: Strategy = {agent: {} for agent in game.agents}
        for (agent, player_type), action in zip(coordinates, selected_actions, strict=True):
            strategy[agent][player_type] = action
        signature = _signature(game, strategy)
        successors[signature] = strategy
    return [successors[signature] for signature in sorted(successors)]


def level_k_prediction(game: BayesianGame, level0: object, k: int) -> list[Strategy]:
    """Return every strategy reachable after ``k`` synchronous best-response rounds.

    ``level0`` is a caller-supplied modeling assumption and is never hard-coded.
    Each round responds to a complete strategy from the preceding round; exact
    ties branch into all maximizing actions and every branch is carried forward.
    Returned strategy profiles are deduplicated and ordered deterministically.
    A zero-step prediction is the supplied anchor as a one-element list.
    """
    if not isinstance(game, BayesianGame):
        raise SpecError("game must be a BayesianGame")
    if type(k) is not int or k < 0:
        raise SpecError("k must be a nonnegative integer")
    if (
        pure_strategy_profile_count(game.agents, game.types, game.actions)
        > MAX_PURE_STRATEGY_PROFILES
    ):
        raise SpecError(f"pure strategy profile count exceeds cap {MAX_PURE_STRATEGY_PROFILES}")

    strategies = [_normalize_strategy(game, level0)]
    seen_states: dict[tuple[StrategySignature, ...], int] = {}
    step = 0
    while step < k:
        state = tuple(_signature(game, strategy) for strategy in strategies)
        previous_step = seen_states.get(state)
        if previous_step is None:
            seen_states[state] = step
        else:
            cycle_length = step - previous_step
            jumps = (k - step) // cycle_length
            if jumps:
                step += jumps * cycle_length
                continue

        successors: dict[StrategySignature, Strategy] = {}
        for previous in strategies:
            for response in _best_response_profiles(game, previous):
                signature = _signature(game, response)
                successors[signature] = response
        strategies = [successors[signature] for signature in sorted(successors)]
        step += 1
    return strategies


__all__ = ["Strategy", "level_k_prediction"]
