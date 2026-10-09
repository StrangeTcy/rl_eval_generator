"""Ground-truth render forms and leakage scanning (V2/V1 support layer).

Source grounding: final review round of ``mission-02/code snippets critique.md``
(fable-5: "GT render-forms + leakage scanner ... leakage scanning covers exact
*and* decimal disguises", with the named test ``test_leakage_decimal_disguise``
— "4/7 vs 0.571"). A renderer that strips the exact fraction ``4/7`` but prints
``0.571`` has still leaked the oracle; scanning must cover the disguises a
rendering plausibly uses.

The scanner is deliberately conservative: it reports candidate matches between
public text and the render forms of ground-truth rationals. A hit is evidence
to inspect, not an automatic verdict — e.g. ``0.50`` may be a legitimately
public prior. Disposition stays with the caller.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, FrozenSet, Mapping, Tuple

from .event_bayes import exact_fraction, require

__all__ = ["gt_render_forms", "leakage_report"]

DEFAULT_DECIMALS: Tuple[int, ...] = (2, 3, 4, 6)


def gt_render_forms(value, *, decimals: Tuple[int, ...] = DEFAULT_DECIMALS,
                    include_complements: bool = True) -> FrozenSet[str]:
    """All plausible textual renderings of one exact ground-truth rational.

    Covers: the exact fraction ``a/b`` (when not an integer), the integer
    itself, fixed-point decimals at each precision in ``decimals`` (both the
    literal fixed form and the trailing-zero-trimmed form), percentages at 1
    decimal, and — when ``include_complements`` — the same forms for ``1 - v``
    (a renderer printing P(W2) instead of P(W1) still leaks the same secret).
    """
    value = exact_fraction(value)
    require(Fraction(0) <= value <= Fraction(1),
            "ground-truth render forms are defined for probabilities in [0, 1]")
    forms = set()

    def add_all(v: Fraction) -> None:
        if v.denominator == 1:
            forms.add(str(v.numerator))
        else:
            forms.add(f"{v.numerator}/{v.denominator}")
        for places in decimals:
            fixed = f"{float(v):.{places}f}"
            forms.add(fixed)
            forms.add(fixed.rstrip("0").rstrip("."))
        pct = float(v) * 100.0
        forms.add(f"{pct:.1f}%")

    add_all(value)
    if include_complements:
        add_all(Fraction(1) - value)
    return frozenset(forms)


def leakage_report(text: str, ground_truth: Mapping[str, object],
                   *, decimals: Tuple[int, ...] = DEFAULT_DECIMALS) -> Dict[str, object]:
    """Scan public ``text`` for render forms of each named ground-truth value.

    Returns ``{"fields": {field: sorted matched forms}, "leaked": bool}``.
    Fields whose only matches are trivially public shapes (``0``, ``1``,
    ``0.00``, ``1.00``, ``0%``, ``100%``) are still reported — suppressing
    them here would be a silent disposition decision.
    """
    if not isinstance(text, str):
        raise TypeError("text must be the rendered public string")
    fields: Dict[str, list] = {}
    for name, value in ground_truth.items():
        matched = sorted(form for form in gt_render_forms(value, decimals=decimals)
                         if form in text)
        if matched:
            fields[name] = matched
    return {"fields": fields, "leaked": bool(fields)}
