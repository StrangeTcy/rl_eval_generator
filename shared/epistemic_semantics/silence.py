"""CS007 deterministic silence: design and result accepted by the user.

Rules are pure Boolean predicates. Fraction output is exact, not support for
probabilistic agent rules or an assumption of independence between agents.
"""
from collections.abc import Callable, Mapping
from fractions import Fraction

from .supplied_policy import Dist, SuppliedPolicyInstance, bayes_update
from .event_bayes import SpecError

Protocol = Mapping[str, Callable[[str], bool]]


def silence_event_likelihood(world: str, protocol: Protocol) -> Fraction:
    """One iff no agent announces; zero otherwise. Empty protocol means silence.

    Evaluate all rules, without any() short-circuiting, and require actual bool
    results. Exceptions from rule evaluation propagate to the caller.
    """
    decisions = [rule(world) for rule in protocol.values()]
    if any(type(decision) is not bool for decision in decisions):
        raise SpecError('deterministic protocol rules must return bool')
    return Fraction(0) if any(decisions) else Fraction(1)


def update_on_silence(prior: Dist, protocol: Protocol) -> Dist:
    policy = {}
    for world in prior:
        likelihood = silence_event_likelihood(world, protocol)
        policy[world] = {'silence': likelihood, 'announcement': 1 - likelihood}
    # announcement is the aggregate complement: at least one agent announces.
    inst = SuppliedPolicyInstance(prior=prior, policy=policy,
                                  realized_observation='silence')
    return bayes_update(inst)
