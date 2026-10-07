"""Accepted CS002 relational and partition-validated S5 interfaces.

General modal accessibility is not automatically S5 knowledge.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class ModelError(ValueError):
    pass


@dataclass(frozen=True)
class World:
    id: str
    properties: Mapping[str, Any]

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ModelError("world ID must be a nonempty string")
        # Snapshot top-level entries; no claim of deep immutability for Any values.
        object.__setattr__(self, "properties", MappingProxyType(dict(self.properties)))


def world_registry(worlds: Iterable[World]) -> Mapping[str, World]:
    registry = {}
    for world in worlds:
        if world.id in registry:
            raise ModelError(f"duplicate world ID: {world.id}")
        registry[world.id] = world
    return MappingProxyType(registry)


class EpistemicModel:
    """General relational model; knows evaluates universal modal accessibility.

    Agents are explicitly declared. An agent with no outgoing edges at a known
    world has an intentionally empty accessibility set, not missing agent data.
    Such an evaluation is vacuously true, as in standard universal semantics.
    """

    def __init__(self, worlds: Iterable[World], agents: Iterable[str]):
        self.worlds = world_registry(worlds)
        agents = tuple(agents)
        if any(not isinstance(a, str) or not a for a in agents) or len(set(agents)) != len(agents):
            raise ModelError("agents must have unique nonempty string IDs")
        self._relations = {agent: set() for agent in agents}

    @property
    def agents(self) -> tuple[str, ...]:
        return tuple(self._relations)

    @property
    def relations(self):
        return MappingProxyType({a: frozenset(edges) for a, edges in self._relations.items()})

    def _check_reference(self, agent, world_id):
        if agent not in self._relations:
            raise ModelError(f"unknown agent: {agent}")
        if world_id not in self.worlds:
            raise ModelError(f"unknown world: {world_id}")

    def add_relation(self, agent: str, w1: str, w2: str):
        self._check_reference(agent, w1)
        self._check_reference(agent, w2)
        self._relations[agent].add((w1, w2))

    def accessible(self, agent: str, world_id: str) -> frozenset[str]:
        self._check_reference(agent, world_id)
        return frozenset(target for source, target in self._relations[agent] if source == world_id)

    def knows(self, agent: str, world_id: str, formula: Callable[[World], bool]) -> bool:
        """Universal modality; the method name alone asserts no frame axioms."""
        return all(formula(self.worlds[target]) for target in self.accessible(agent, world_id))


class S5EpistemicModel:
    """Separate partition-validated interface; no general edge-mutation method.

    Each declared agent's nonempty, disjoint cells cover exactly all worlds.
    Equality of cell membership therefore supplies reflexivity, symmetry and
    transitivity. At every existing world accessibility includes that world.
    """

    def __init__(self, worlds: Iterable[World], partitions: Mapping[str, Iterable[Iterable[str]]]):
        self.worlds = world_registry(worlds)
        checked = {}
        for agent, raw_cells in partitions.items():
            if not isinstance(agent, str) or not agent:
                raise ModelError("agent ID must be a nonempty string")
            cells = tuple(frozenset(cell) for cell in raw_cells)
            seen = set()
            for cell in cells:
                if not cell or not cell <= self.worlds.keys():
                    raise ModelError("empty cell or dangling world reference")
                if seen & cell:
                    raise ModelError("overlapping partition cells")
                seen.update(cell)
            if seen != set(self.worlds):
                raise ModelError("partition must cover exactly the known worlds")
            checked[agent] = cells
        self.partitions = MappingProxyType(checked)

    @property
    def agents(self) -> tuple[str, ...]:
        return tuple(self.partitions)

    def accessible(self, agent: str, world_id: str) -> frozenset[str]:
        if agent not in self.partitions:
            raise ModelError(f"unknown agent: {agent}")
        if world_id not in self.worlds:
            raise ModelError(f"unknown world: {world_id}")
        return next(cell for cell in self.partitions[agent] if world_id in cell)

    def knows(self, agent: str, world_id: str, formula: Callable[[World], bool]) -> bool:
        return all(formula(self.worlds[target]) for target in self.accessible(agent, world_id))
