"""Boundary tests for shared/epistemic_semantics/bayes.py.

Named by the final critique blueprint: "LR==3 boundary; asymmetric-prior
transposition" plus exactness and zero-evidence rejection. These falsify the
failure modes the blueprint calls out: float drift at band edges, swapped
likelihood tables hiding behind symmetric priors, and silent renormalization
of impossible observations.
"""
from __future__ import annotations

from fractions import Fraction

import pytest

from shared.epistemic_semantics import bayes
from shared.epistemic_semantics.event_bayes import SpecError


def test_verdict_band_boundary_at_exactly_three() -> None:
    # R == 3 exactly is "distinguishable"; anything below is weak. Exact
    # arithmetic keeps the boundary decidable (float 2.9999999... mis-bins).
    assert bayes.likelihood_ratio_band(Fraction(3), Fraction(1))[1] == "distinguishable"
    assert bayes.likelihood_ratio_band(Fraction(2999999, 1000000), Fraction(1))[1] == (
        "weakly_distinguishable"
    )
    assert bayes.likelihood_ratio_band(Fraction(1), Fraction(1))[1] == "indistinguishable"
    ratio, _ = bayes.likelihood_ratio_band(Fraction(3), Fraction(1))
    assert ratio == Fraction(3)


def test_ratio_is_symmetric_but_posterior_is_not() -> None:
    # R is unsigned; the posterior must still move in the right direction.
    r_ab, verdict_ab = bayes.likelihood_ratio_band(Fraction(4, 5), Fraction(1, 5))
    r_ba, verdict_ba = bayes.likelihood_ratio_band(Fraction(1, 5), Fraction(4, 5))
    assert r_ab == r_ba == Fraction(4)
    assert verdict_ab == verdict_ba == "distinguishable"
    assert bayes.posterior_world1(Fraction(1, 2), Fraction(4, 5), Fraction(1, 5)) == Fraction(4, 5)
    assert bayes.posterior_world1(Fraction(1, 2), Fraction(1, 5), Fraction(4, 5)) == Fraction(1, 5)


def test_asymmetric_prior_catches_transposed_likelihoods() -> None:
    # The unsigned ratio (and the verdict band built on it) is blind to a
    # transposed likelihood table for ANY prior: R(L1, L2) == R(L2, L1).
    # Only the directional posterior catches the swap; with an asymmetric
    # prior the transposed posterior is not even the complement, so verdict-
    # only checks must never substitute for posterior checks.
    l1, l2 = Fraction(9, 10), Fraction(1, 10)
    r_right, verdict_right = bayes.likelihood_ratio_band(l1, l2)
    r_swap, verdict_swap = bayes.likelihood_ratio_band(l2, l1)
    assert (r_right, verdict_right) == (r_swap, verdict_swap)  # band is blind

    for prior in (Fraction(1, 2), Fraction(3, 5)):
        right = bayes.posterior_world1(prior, l1, l2)
        transposed = bayes.posterior_world1(prior, l2, l1)
        assert right > Fraction(1, 2) > transposed
    # Balanced prior: the swap lands exactly on the complement.
    assert bayes.posterior_world1(Fraction(1, 2), l1, l2) == Fraction(9, 10)
    assert bayes.posterior_world1(Fraction(1, 2), l2, l1) == Fraction(1, 10)
    # Skewed prior: not even the complement (3/21 = 1/7).
    assert bayes.posterior_world1(Fraction(3, 5), l2, l1) == Fraction(1, 7)


def test_zero_evidence_is_rejected_not_renormalized() -> None:
    with pytest.raises(SpecError):
        bayes.posterior_world1(Fraction(1, 2), Fraction(0), Fraction(0))
    with pytest.raises(SpecError):
        bayes.likelihood_ratio_band(Fraction(0), Fraction(1, 2))


def test_float_inputs_are_rejected() -> None:
    # Exactness rule: categorical labels must never be derived from floats.
    with pytest.raises(SpecError):
        bayes.posterior_world1(0.5, Fraction(1), Fraction(1))
    with pytest.raises(SpecError):
        bayes.likelihood_ratio_band(0.75, Fraction(1, 4))


def test_exact_result_at_thirds() -> None:
    # 1/3*1/2 : 2/3*1/4 = 1/6 : 1/6 -> exactly 1/2 (floats drift off this).
    posterior = bayes.posterior_world1(Fraction(1, 3), Fraction(1, 2), Fraction(1, 4))
    assert posterior == Fraction(1, 2)


def test_approved_contracts_reexported_unchanged() -> None:
    from shared.epistemic_semantics import event_bayes, supplied_policy

    assert bayes.FiniteDist is event_bayes.FiniteDist
    assert bayes.calculate_posterior_strict is event_bayes.calculate_posterior_strict
    assert bayes.SuppliedPolicyInstance is supplied_policy.SuppliedPolicyInstance
    assert bayes.bayes_update is supplied_policy.bayes_update
