"""Accepted CS005 propositional S5 models and callable announcements.

Reuses CS002 partition validation. Formula callbacks are mathematical
predicates: they must be pure and return bool.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from epistemic_relations import ModelError, S5EpistemicModel
from epistemic_relations import World as WorldRecord

World = str
Agent = str


@dataclass(frozen=True)
class EpistemicModel:
    worlds: frozenset[World]
    partitions: Mapping[Agent, frozenset[frozenset[World]]]
    valuation: Mapping[World, frozenset[str]]

    def __post_init__(self):
        worlds = frozenset(self.worlds)
        # Keep this source's propositional interface; reuse accepted validation,
        # rather than duplicating or silently weakening the S5 frame conditions.
        frame = S5EpistemicModel([WorldRecord(world, {}) for world in worlds], self.partitions)
        if set(self.valuation) != set(worlds):
            raise ModelError("valuation must cover exactly the model worlds")
        object.__setattr__(self, "worlds", worlds)
        object.__setattr__(
            self,
            "partitions",
            MappingProxyType(
                {agent: frozenset(cells) for agent, cells in frame.partitions.items()}
            ),
        )
        object.__setattr__(
            self,
            "valuation",
            MappingProxyType({world: frozenset(props) for world, props in self.valuation.items()}),
        )

    def agent_class(self, agent: Agent, world: World) -> frozenset[World]:
        if agent not in self.partitions:
            raise ModelError(f"unknown agent: {agent}")
        if world not in self.worlds:
            raise ModelError(f"unknown world: {world}")
        return next(cell for cell in self.partitions[agent] if world in cell)


Formula = Callable[[EpistemicModel, World], bool]


def atom(proposition: str) -> Formula:
    def evaluate(model, world):
        if world not in model.worlds:
            raise ModelError(f"unknown world: {world}")
        return proposition in model.valuation[world]

    return evaluate


def neg(formula: Formula) -> Formula:
    return lambda model, world: not formula(model, world)


def knows(agent: Agent, formula: Formula) -> Formula:
    return lambda model, world: all(
        formula(model, alternative) for alternative in model.agent_class(agent, world)
    )


def _restrict(model: EpistemicModel, surviving: frozenset[World]) -> EpistemicModel:
    if not surviving:
        raise ModelError("announcement eliminates every world")
    return EpistemicModel(
        surviving,
        {
            agent: frozenset(cell & surviving for cell in cells if cell & surviving)
            for agent, cells in model.partitions.items()
        },
        {world: model.valuation[world] for world in surviving},
    )


def public_announce(model: EpistemicModel, formula: Formula) -> EpistemicModel:
    """Unpointed source operation: restrict by truth in the current model."""
    surviving = frozenset(world for world in model.worlds if formula(model, world))
    return _restrict(model, surviving)


def announce_sequence(model: EpistemicModel, formulas: Iterable[Formula]) -> EpistemicModel:
    for formula in formulas:
        model = public_announce(model, formula)
    return model


def public_announce_checked(
    model: EpistemicModel, actual_world: World, formula: Formula
) -> EpistemicModel:
    """Separate pointed check: actual world must exist and satisfy the formula.

    All truth values are evaluated in the pre-update model. The actual world's
    predicate is not evaluated a second time; its membership in surviving is
    the same truth check used to construct the restriction.
    """
    if actual_world not in model.worlds:
        raise ModelError(f"unknown actual world: {actual_world}")
    surviving = frozenset(world for world in model.worlds if formula(model, world))
    if actual_world not in surviving:
        raise ModelError("announcement is false at the actual world")
    return _restrict(model, surviving)


def announce_sequence_checked(
    model: EpistemicModel, actual_world: World, formulas: Iterable[Formula]
) -> EpistemicModel:
    if actual_world not in model.worlds:
        raise ModelError(f"unknown actual world: {actual_world}")
    for formula in formulas:
        model = public_announce_checked(model, actual_world, formula)
    return model
