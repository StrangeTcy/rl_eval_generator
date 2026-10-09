"""Exact epistemic-game semantics shared across generator families and oracles.

Provenance and contract rules (user-approved 2026-10-07)
---------------------------------------------------------
The seven ``CS001``–``CS011`` modules below were accepted at epistemic-compiler
revision ``cdd03a2365174250d32b89d970be85bae21c7998`` (see
``mission-02/snippet_reconciliation/approved/`` in StrangeTcy/epistemic-compiler)
and are vendored here with bodies byte-identical to the accepted artifacts;
only import lines were transformed for package placement (see
``APPROVED_SOURCES.md``).

Contract rules:

* Accepted modules are frozen contracts. Later code may import, wrap, or extend
  them. It must never silently replace them or alter their semantics; any such
  change requires explicit user authorization.
* Exact ``fractions.Fraction`` arithmetic everywhere a categorical label is
  derived. Floats are display/post-hoc statistics only.
* These modules carry no ground truth of any generated instance. They are
  mathematical infrastructure; instance secrets stay in judge-side specs.
"""
from __future__ import annotations

__all__ = [
    "common_knowledge",
    "epistemic_relations",
    "event_bayes",
    "fragmented_observation",
    "public_announcements",
    "silence",
    "supplied_policy",
]
