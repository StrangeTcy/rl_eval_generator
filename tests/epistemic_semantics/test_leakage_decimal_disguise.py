"""Leakage-scanner tests (blueprint: "4/7 vs 0.571" decimal disguises).

A renderer that strips the exact fraction but prints a decimal or percent
rounding has still leaked the ground truth; scanning must cover the disguises.
"""
from __future__ import annotations

from fractions import Fraction

from shared.epistemic_semantics.leakage import gt_render_forms, leakage_report


def test_exact_and_decimal_disguises_are_render_forms() -> None:
    forms = gt_render_forms(Fraction(4, 7))
    assert "4/7" in forms
    assert "0.571" in forms          # 3-dp rounding of 4/7
    assert "0.5714" in forms         # 4-dp rounding
    assert "57.1%" in forms
    # complement forms: a renderer printing P(W2) leaks the same secret
    assert "3/7" in forms
    assert "0.429" in forms


def test_integer_probabilities_do_not_spawn_fractions() -> None:
    forms = gt_render_forms(Fraction(1))
    assert "1" in forms and "1.00" in forms and "100.0%" in forms
    assert "1/1" not in forms


def test_report_flags_decimal_disguise_leak() -> None:
    text = "The posterior works out to roughly 0.571 in this case."
    report = leakage_report(text, {"posterior_world1": Fraction(4, 7)})
    assert report["leaked"] is True
    assert "0.571" in report["fields"]["posterior_world1"]


def test_report_ignores_unrelated_text() -> None:
    report = leakage_report(
        "No numbers worth quoting here.", {"posterior_world1": Fraction(4, 7)}
    )
    assert report["leaked"] is False and report["fields"] == {}


def test_complement_disguise_is_caught() -> None:
    report = leakage_report(
        "chance of the other world: 42.9%", {"posterior_world1": Fraction(4, 7)}
    )
    assert report["leaked"] is True
    assert "42.9%" in report["fields"]["posterior_world1"]


def test_trivial_public_values_are_still_reported_not_suppressed() -> None:
    # 0.50 may be a legitimately public prior; disposition belongs to the
    # caller, so the scanner reports rather than silently dropping it.
    report = leakage_report("prior is 0.50", {"posterior": Fraction(1, 2)})
    assert report["leaked"] is True
