"""Exact bounded finite Bayesian games and pure-BNE enumeration.

This is the E6 semantic component used by the epistemic_reasoning task engine.
The payoff callback is evaluated on complete type/action profiles; the JSON
adapter reconstructs it from a frozen exact-rational payoff table.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from types import MappingProxyType
from typing import Any

from event_bayes import SpecError, exact_fraction

Agent = str
PlayerType = str
Action = str
TypeProfile = tuple[PlayerType, ...]
ActionProfile = tuple[Action, ...]
Utility = Callable[[Mapping[Agent, PlayerType], Mapping[Agent, Action]], Mapping[Agent, Any]]

MAX_PURE_STRATEGY_PROFILES = 20_000


def _labels(values: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise SpecError(f"{label} must be a nonempty sequence")
    copied = tuple(values)
    if any(type(value) is not str or not value for value in copied):
        raise SpecError(f"{label} must contain nonempty string IDs")
    if len(set(copied)) != len(copied):
        raise SpecError(f"{label} IDs must be unique")
    return copied


def pure_strategy_profile_count(
    agents: tuple[Agent, ...],
    types: Mapping[Agent, tuple[PlayerType, ...]],
    actions: Mapping[Agent, tuple[Action, ...]],
) -> int:
    """Count pure strategy profiles before constructing the Cartesian product."""
    count = 1
    for agent in agents:
        count *= len(actions[agent]) ** len(types[agent])
    return count


@dataclass(frozen=True)
class BayesianGame:
    """A finite type space with a common prior and exact utility callback.

    The callback should be deterministic and have no external side effects.
    Game-owned mappings are snapshotted; the callback receives fresh ordinary
    dictionaries to preserve the source calling convention. Results are checked
    at every use for complete player coverage and exact rational values.
    """

    agents: tuple[Agent, ...]
    types: Mapping[Agent, tuple[PlayerType, ...]]
    common_prior: Mapping[TypeProfile, Fraction]
    actions: Mapping[Agent, tuple[Action, ...]]
    utility: Utility

    def __post_init__(self) -> None:
        if not isinstance(self.agents, (tuple, list)):
            raise SpecError("agents must be an ordered sequence")
        agents = tuple(self.agents)
        if not agents or any(type(agent) is not str or not agent for agent in agents):
            raise SpecError("agents must be nonempty string IDs")
        if len(set(agents)) != len(agents):
            raise SpecError("agent IDs must be unique")
        if not isinstance(self.types, Mapping) or set(self.types) != set(agents):
            raise SpecError("types must define exactly the declared agents")
        if not isinstance(self.actions, Mapping) or set(self.actions) != set(agents):
            raise SpecError("actions must define exactly the declared agents")

        types = MappingProxyType(
            {agent: _labels(self.types[agent], label=f"types[{agent}]") for agent in agents}
        )
        actions = MappingProxyType(
            {agent: _labels(self.actions[agent], label=f"actions[{agent}]") for agent in agents}
        )
        strategy_count = pure_strategy_profile_count(agents, types, actions)
        if strategy_count > MAX_PURE_STRATEGY_PROFILES:
            raise SpecError(
                f"pure strategy profile count {strategy_count} exceeds cap "
                f"{MAX_PURE_STRATEGY_PROFILES}"
            )
        if not callable(self.utility):
            raise SpecError("utility must be a callable over type and action profiles")

        if not isinstance(self.common_prior, Mapping) or not self.common_prior:
            raise SpecError("common_prior must be a nonempty type-profile distribution")
        prior: dict[TypeProfile, Fraction] = {}
        for profile, raw_probability in self.common_prior.items():
            if type(profile) is not tuple or len(profile) != len(agents):
                raise SpecError("common-prior keys must be ordered type tuples matching agents")
            if any(
                type(profile[index]) is not str or profile[index] not in types[agent]
                for index, agent in enumerate(agents)
            ):
                raise SpecError("common_prior contains an undeclared type profile")
            probability = exact_fraction(raw_probability)
            if probability < 0:
                raise SpecError("common_prior cannot contain negative probability mass")
            prior[profile] = probability
        if sum(prior.values(), Fraction(0)) != 1:
            raise SpecError("common_prior must sum exactly to one")
        for index, agent in enumerate(agents):
            for player_type in types[agent]:
                marginal = sum(
                    probability
                    for profile, probability in prior.items()
                    if profile[index] == player_type
                )
                if marginal == 0:
                    raise SpecError(f"declared type has zero marginal prior: {agent}:{player_type}")

        raw_utility = self.utility

        def frozen_utility(
            type_assignment: Mapping[Agent, PlayerType],
            action_assignment: Mapping[Agent, Action],
        ) -> Mapping[Agent, Fraction]:
            if not isinstance(type_assignment, Mapping) or set(type_assignment) != set(agents):
                raise SpecError("utility type assignment must cover exactly the agents")
            if not isinstance(action_assignment, Mapping) or set(action_assignment) != set(agents):
                raise SpecError("utility action assignment must cover exactly the agents")
            copied_types = {agent: type_assignment[agent] for agent in agents}
            copied_actions = {agent: action_assignment[agent] for agent in agents}
            if any(copied_types[agent] not in types[agent] for agent in agents):
                raise SpecError("utility called with an undeclared type")
            if any(copied_actions[agent] not in actions[agent] for agent in agents):
                raise SpecError("utility called with an undeclared action")
            result = raw_utility(copied_types, copied_actions)
            if not isinstance(result, Mapping) or set(result) != set(agents):
                raise SpecError("utility must return exactly one payoff per agent")
            return {agent: exact_fraction(result[agent]) for agent in agents}

        object.__setattr__(self, "agents", agents)
        object.__setattr__(self, "types", types)
        object.__setattr__(self, "actions", actions)
        object.__setattr__(self, "common_prior", MappingProxyType(prior))
        object.__setattr__(self, "utility", frozen_utility)


def _validated_strategy(
    game: BayesianGame, strategy: object
) -> dict[Agent, Mapping[PlayerType, Action]]:
    if not isinstance(strategy, Mapping) or set(strategy) != set(game.agents):
        raise SpecError("strategy must define exactly the declared agents")
    result: dict[Agent, Mapping[PlayerType, Action]] = {}
    for agent in game.agents:
        rows = strategy[agent]
        if not isinstance(rows, Mapping) or set(rows) != set(game.types[agent]):
            raise SpecError(f"strategy must define exactly every type of {agent}")
        copied = dict(rows)
        if any(action not in game.actions[agent] for action in copied.values()):
            raise SpecError(f"strategy for {agent} uses an undeclared action")
        result[agent] = MappingProxyType(copied)
    return result


def _expected_utilities_for_type(
    game: BayesianGame,
    agent: Agent,
    own_type: PlayerType,
    strategy: Mapping[Agent, Mapping[PlayerType, Action]],
) -> dict[Action, Fraction]:
    if agent not in game.agents or own_type not in game.types[agent]:
        raise SpecError(f"unknown agent/type: {agent}:{own_type}")
    agent_index = game.agents.index(agent)
    marginal = sum(
        probability
        for profile, probability in game.common_prior.items()
        if profile[agent_index] == own_type
    )
    if marginal == 0:
        raise SpecError(f"declared type has zero marginal prior: {agent}:{own_type}")

    totals = {action: Fraction(0) for action in game.actions[agent]}
    for type_profile, probability in game.common_prior.items():
        if probability == 0 or type_profile[agent_index] != own_type:
            continue
        types_at_profile = dict(zip(game.agents, type_profile, strict=True))
        actions_at_profile = {
            other: strategy[other][types_at_profile[other]] for other in game.agents
        }
        for action in game.actions[agent]:
            deviating_actions = dict(actions_at_profile)
            deviating_actions[agent] = action
            payoff = game.utility(types_at_profile, deviating_actions)[agent]
            totals[action] += probability * payoff
    return {action: value / marginal for action, value in totals.items()}


def expected_utilities(
    game: BayesianGame,
    agent: Agent,
    strategy: object,
    own_type: PlayerType,
) -> Mapping[Action, Fraction]:
    """Return exact conditional expected utility for each action at a type."""
    normalized = _validated_strategy(game, strategy)
    return MappingProxyType(_expected_utilities_for_type(game, agent, own_type, normalized))


def is_best_response_everywhere(game: BayesianGame, strategy: object) -> bool:
    """Check every positive-prior type's pure best-response condition exactly."""
    normalized = _validated_strategy(game, strategy)
    for agent in game.agents:
        for own_type in game.types[agent]:
            utilities = _expected_utilities_for_type(game, agent, own_type, normalized)
            if utilities[normalized[agent][own_type]] != max(utilities.values()):
                return False
    return True


def enumerate_pure_bayesian_nash_equilibria(
    game: BayesianGame,
) -> list[dict[Agent, dict[PlayerType, Action]]]:
    """Enumerate the complete pure-strategy BNE set for a bounded finite game.

    This exhaustively evaluates every pure strategy profile independently of a
    submitted candidate. It shares the exact best-response predicate with the
    exposed checker and does not solve for mixed equilibria.
    """
    if (
        pure_strategy_profile_count(game.agents, game.types, game.actions)
        > MAX_PURE_STRATEGY_PROFILES
    ):
        raise SpecError(f"pure strategy profile count exceeds cap {MAX_PURE_STRATEGY_PROFILES}")
    per_agent_strategies: list[list[dict[PlayerType, Action]]] = []
    for agent in game.agents:
        per_agent_strategies.append(
            [
                dict(zip(game.types[agent], selected_actions, strict=True))
                for selected_actions in product(game.actions[agent], repeat=len(game.types[agent]))
            ]
        )

    equilibria: list[dict[Agent, dict[PlayerType, Action]]] = []
    for strategy_tuple in product(*per_agent_strategies):
        strategy = {agent: strategy_tuple[index] for index, agent in enumerate(game.agents)}
        if is_best_response_everywhere(game, strategy):
            equilibria.append({agent: dict(strategy[agent]) for agent in game.agents})
    return equilibria


__all__ = [
    "MAX_PURE_STRATEGY_PROFILES",
    "BayesianGame",
    "enumerate_pure_bayesian_nash_equilibria",
    "expected_utilities",
    "is_best_response_everywhere",
    "pure_strategy_profile_count",
]
