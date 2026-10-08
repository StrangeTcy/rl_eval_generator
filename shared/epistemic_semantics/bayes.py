"""Exact two-hypothesis Bayes primitives (blueprint ``bayes.py`` layer).

Source grounding: final review round of ``mission-02/code snippets critique.md``
(fable-5, CS079 block: "FiniteDist, SuppliedPolicyInstance, lr_verdict — exact
only") and proposal v2's shared exact-arithmetic section. Per the approved-
contract rule, this module is a thin layer OVER the accepted CS001/CS003–006
modules (``event_bayes``, ``supplied_policy``): it re-exports their contracts
and adds the two-world posterior and likelihood-ratio verdict band used by the
``epistemic_games`` family, without re-implementing the update math.

Exactness rule: every value that feeds a categorical label (verdict band,
support direction) is a ``fractions.Fraction``. Floats are display-only.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, Tuple

from .event_bayes import (  # accepted CS001 contracts (frozen)
    EpistemicEvent,
    FiniteDist,
    SpecError,
    calculate_posterior,
    calculate_posterior_sparse,
    calculate_posterior_strict,
    exact_fraction,
    require,
)
from .supplied_policy import (  # accepted CS003–CS006 contracts (frozen)
    SparseSuppliedPolicyInstance,
    StrictSuppliedPolicyInstance,
    SuppliedPolicyInstance,
    bayes_update,
    validate_dist,
)

__all__ = [
    "EpistemicEvent", "FiniteDist", "SpecError", "calculate_posterior",
    "calculate_posterior_sparse", "calculate_posterior_strict", "exact_fraction",
    "require", "SparseSuppliedPolicyInstance", "StrictSuppliedPolicyInstance",
    "SuppliedPolicyInstance", "bayes_update", "validate_dist",
    "VERDICT_INDISTINGUISHABLE", "VERDICT_WEAK", "VERDICT_STRONG", "VERDICTS",
    "WEAK_STRONG_RATIO", "posterior_world1", "likelihood_ratio_band",
]

# Verdict bands on the likelihood ratio R = max(L1/L2, L2/L1):
#   indistinguishable          R == 1        (total non-identifiability)
#   weakly_distinguishable     1 < R < 3     (valid, weak inference)
#   distinguishable            R >= 3        (valid, strong inference)
# These are the v0 epistemic_games bands (kept identical on refactor); the
# E1 question card notes the verdict uses UNSIGNED strength R — directional
# analyses must use the signed log likelihood ratio separately.
VERDICT_INDISTINGUISHABLE = "indistinguishable"
VERDICT_WEAK = "weakly_distinguishable"
VERDICT_STRONG = "distinguishable"
VERDICTS: Tuple[str, ...] = (VERDICT_INDISTINGUISHABLE, VERDICT_WEAK, VERDICT_STRONG)

WEAK_STRONG_RATIO = Fraction(3)


def posterior_world1(prior1: Fraction, likelihood1: Fraction,
                     likelihood2: Fraction) -> Fraction:
    """Exact P(W1 | o) for two exhaustive worlds.

    ``prior1`` is P(W1); the prior over W2 is ``1 - prior1``. Raises SpecError
    unless all inputs are exact, priors are in [0, 1], likelihoods are in
    [0, 1], and the observation has positive marginal probability.
    """
    prior1 = exact_fraction(prior1)
    likelihood1 = exact_fraction(likelihood1)
    likelihood2 = exact_fraction(likelihood2)
    require(Fraction(0) <= prior1 <= Fraction(1), "prior outside [0, 1]")
    require(Fraction(0) <= likelihood1 <= Fraction(1), "likelihood1 outside [0, 1]")
    require(Fraction(0) <= likelihood2 <= Fraction(1), "likelihood2 outside [0, 1]")
    evidence = likelihood1 * prior1 + likelihood2 * (Fraction(1) - prior1)
    if evidence == 0:
        raise SpecError("observed event has zero probability under the prior's support")
    return likelihood1 * prior1 / evidence


def likelihood_ratio_band(likelihood1: Fraction, likelihood2: Fraction,
                          *, weak_strong_ratio: Fraction = WEAK_STRONG_RATIO,
                          ) -> Tuple[Fraction, str]:
    """Return ``(R, verdict)`` with ``R = max(L1/L2, L2/L1)`` exact.

    Bands: ``R == 1`` indistinguishable; ``1 < R < weak_strong_ratio`` weakly
    distinguishable; ``R >= weak_strong_ratio`` distinguishable. Both
    likelihoods must be strictly positive exact rationals (a zero likelihood
    means the observation itself was ill-posed for that world).
    """
    likelihood1 = exact_fraction(likelihood1)
    likelihood2 = exact_fraction(likelihood2)
    require(likelihood1 > 0 and likelihood2 > 0,
            "likelihood ratio is undefined for zero likelihoods")
    ratio = max(likelihood1 / likelihood2, likelihood2 / likelihood1)
    if ratio == 1:
        verdict = VERDICT_INDISTINGUISHABLE
    elif ratio < weak_strong_ratio:
        verdict = VERDICT_WEAK
    else:
        verdict = VERDICT_STRONG
    return ratio, verdict
