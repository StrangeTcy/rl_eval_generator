"""CS003 proposal correction; design and result accepted by the user.

Depends on the accepted CS001 event_bayes module, not target-repository code.
Sparse and strict policy tables are separate contracts. Both validate full
probability rows at construction, but defer zero-evidence rejection to update.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from .event_bayes import (
    EpistemicEvent, FiniteDist, SpecError, calculate_posterior_strict, require,
)


Dist = Mapping[str, Fraction]


def validate_dist(d: Dist, *, label: str) -> None:
    """Preserved source interface; use CS001's approved exact validator."""
    try:
        FiniteDist(d)
    except SpecError as exc:
        raise SpecError(f'{label}: {exc}') from exc


@dataclass(frozen=True)
class SuppliedPolicyInstance:
    """Sparse full-policy rows; missing observations mean zero, not missing worlds.

    A realized label absent from every row is allowed here and has zero evidence.
    Each row must nevertheless be a complete normalized distribution over its
    listed observations. An event-only likelihood vector is not a policy row.
    """
    prior: Dist
    policy: Mapping[str, Dist]
    realized_observation: str

    def __post_init__(self):
        prior = FiniteDist(self.prior)
        require(set(self.policy) == set(prior.mass), 'policy worlds must exactly match prior worlds')
        rows = {}
        for world, row in self.policy.items():
            try:
                rows[world] = FiniteDist(row).mass
            except SpecError as exc:
                raise SpecError(f'policy[{world}]: {exc}') from exc
        object.__setattr__(self, 'prior', prior.mass)
        object.__setattr__(self, 'policy', MappingProxyType(rows))
        # No posterior computation: a zero-evidence observation is rejected on update.


# Explicit sparse name without replacing the source's public class name.
SparseSuppliedPolicyInstance = SuppliedPolicyInstance


@dataclass(frozen=True)
class StrictSuppliedPolicyInstance(SuppliedPolicyInstance):
    """Every row lists exactly the declared alphabet, including explicit zeros."""
    observations: tuple[str, ...]

    def __post_init__(self):
        super().__post_init__()
        observations = tuple(self.observations)
        require(bool(observations) and len(set(observations)) == len(observations),
                'observation alphabet must be nonempty and unique')
        require(all(set(row) == set(observations) for row in self.policy.values()),
                'strict policy rows must exactly cover the observation alphabet')
        require(self.realized_observation in observations, 'undeclared realized observation')
        object.__setattr__(self, 'observations', observations)
        # Declared observation with zero evidence remains legal until update.


def bayes_update(instance: SuppliedPolicyInstance) -> Dist:
    """Project the observed event, then reuse the approved exact event updater.

    This shared computation is not an independent verification implementation.
    Sparse and strict tables both produce a likelihood for every prior world.
    """
    event = EpistemicEvent(
        instance.realized_observation,
        {world: row.get(instance.realized_observation, Fraction(0))
         for world, row in instance.policy.items()},
    )
    return calculate_posterior_strict(instance.prior, event)
