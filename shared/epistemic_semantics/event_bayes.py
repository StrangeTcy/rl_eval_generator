"""Accepted proposal snippet CS001; not integrated into rl_eval_generator.

User approved: named-event API retained, sparse and strict contracts separated,
mathematical core plus validation wrappers. Full-policy API remains separate.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Generic, Hashable, TypeVar

class SpecError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SpecError(message)


def exact_fraction(value):
    require(type(value) in (int, str, Fraction), 'exact int, string or Fraction required')
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise SpecError('invalid rational') from exc


DistKey = TypeVar('DistKey', bound=Hashable)


@dataclass(frozen=True)
class FiniteDist(Generic[DistKey]):
    mass: Mapping[DistKey, Fraction]

    def __post_init__(self):
        copied = {k: exact_fraction(v) for k, v in self.mass.items()}
        require(bool(copied) and all(p >= 0 for p in copied.values()), 'invalid mass')
        require(sum(copied.values(), Fraction(0)) == 1, 'distribution must sum to one')
        object.__setattr__(self, 'mass', MappingProxyType(copied))

    def __getitem__(self, key):
        return self.mass[key]


@dataclass(frozen=True)
class EpistemicEvent:
    name: str
    likelihoods: Mapping[str, Fraction]


def calculate_posterior(prior, event):
    """Mathematical core; caller establishes exact probability preconditions.

    Sparse contract: missing prior-state likelihoods are zero; unrelated event
    entries are ignored. Validation is deliberately in the named wrappers.
    """
    weights = {state: prior[state] * event.likelihoods.get(state, 0) for state in prior}
    evidence = sum(weights.values(), Fraction(0))
    if evidence == 0:
        raise SpecError('Zero-probability event observed.')
    return {state: weight / evidence for state, weight in weights.items()}


def _validated_event_inputs(prior, event):
    validated_prior = FiniteDist(prior)
    # Sparse semantics ignore unrelated keys, including their values.
    likelihoods = {
        state: exact_fraction(event.likelihoods.get(state, 0))
        for state in validated_prior.mass
    }
    require(all(0 <= value <= 1 for value in likelihoods.values()), 'event likelihood out of range')
    return validated_prior.mass, EpistemicEvent(event.name, likelihoods)


def calculate_posterior_sparse(prior, event):
    checked_prior, checked_event = _validated_event_inputs(prior, event)
    return calculate_posterior(checked_prior, checked_event)


def calculate_posterior_strict(prior, event):
    require(set(prior) == set(event.likelihoods), 'strict event support mismatch')
    checked_prior, checked_event = _validated_event_inputs(prior, event)
    return calculate_posterior(checked_prior, checked_event)
