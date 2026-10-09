"""T1 matched-fact presentation primitives (identity fix).

Source grounding (epistemic-compiler corpus, Mission 02):

* ``code snippets critique.md`` section "T1: Matched-fact presentation":
  using text hashes for fact identity is backwards for a matched-fact
  presentation design - the study varies presentation while holding facts
  constant, so identity must be assigned to the fact OBJECT at generation
  time and carried as metadata, never re-derived from rendered text.
* T1 final section: "semantic fact multiset ID + presentation permutation
  arm"; canonicalize structured facts, not English; hashing English loses
  commutativity of fact sets and confuses whitespace noise with fact change.
* Shared-primitive notes: canonical semantic hash is compute-from-structure,
  and paired-arm construction (same instance, one varied thing) is the
  reusable shape for T1 (and later S1/S4).

Scope discipline: this module is the `implementable primitive` for the T1
identity fix. The broader presentation-order-effect question remains
`needs prior-art/source check first` per the corpus; nothing here measures
behavior, and behavioral sensitivity to presentation is explicitly NOT an
attention-mechanism claim.

Contract rules:

* ``canonical_semantic_hash`` and ``semantic_fact_multiset_id`` hash ONLY
  canonical structured content. Rendered text never participates.
* Fact identity is assigned once at generation/extraction time and travels
  with the fact as metadata (``fact_id``).
* The multiset ID is commutative over fact ORDER by construction
  (canonical sorting), and sensitive to fact CONTENT.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

__all__ = [
    "Fact",
    "RenderedPresentation",
    "MatchedFactPair",
    "canonical_semantic_hash",
    "semantic_fact_multiset_id",
    "canonical_content_blob",
    "build_matched_fact_pair",
]


@dataclass(frozen=True)
class Fact:
    """One structured fact with generation-time identity.

    ``fact_id`` is assigned once, at generation/extraction time, before any
    rendering, and is carried through as metadata. ``canonical_content`` is
    the renderer-independent representation that defines the fact's
    identity. ``text`` is ONE presentation of the fact and carries no
    identity weight whatsoever.
    """

    fact_id: str
    canonical_content: Dict[str, object]
    text: str = ""


@dataclass(frozen=True)
class RenderedPresentation:
    """A presentation of a fact set, keyed by fact identity + variant.

    The pair ``(fact_set_id, variant)`` identifies the presentation; the
    rendered text is payload only and must never be hashed for identity.
    """

    fact_set_id: str
    variant: str
    order: Tuple[int, ...]
    text: str


@dataclass(frozen=True)
class MatchedFactPair:
    """Same facts, two presentations - the T1 matched design as data."""

    semantic_fact_id: str
    presentation_a: RenderedPresentation
    presentation_b: RenderedPresentation
    fact_count: int
    fact_ids: Tuple[str, ...] = field(default_factory=tuple)


def canonical_content_blob(canonical_content: Dict[str, object]) -> str:
    """Deterministic JSON serialization of canonical content.

    Sorted keys and compact separators make the blob a function of content
    alone; key insertion order and whitespace never matter.
    """
    return json.dumps(canonical_content, sort_keys=True, separators=(",", ":"))


def canonical_semantic_hash(fact: Fact) -> str:
    """Hash over the CANONICAL structured content, not over any rendered
    text - stable across presentation variants by construction, because the
    renderer never participates in computing it."""
    return hashlib.sha256(canonical_content_blob(fact.canonical_content).encode("utf-8")).hexdigest()


def semantic_fact_multiset_id(facts: Sequence[Fact]) -> str:
    """Canonical ID of a fact MULTISET: commutative over fact order,
    sensitive to fact content.

    Hashing the sorted canonical blobs (not English text) preserves the
    commutativity a matched-fact design requires: reordering presentations
    never changes identity, while any content change does.
    """
    blobs = sorted(canonical_content_blob(fact.canonical_content) for fact in facts)
    payload = "\n".join(blobs).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _check_permutation(order: Sequence[int], n: int, label: str) -> Tuple[int, ...]:
    order = tuple(order)
    if sorted(order) != list(range(n)):
        raise ValueError(f"{label} must be a permutation of range({n}), got {order!r}")
    return order


def render_fact_list(facts: Sequence[Fact], order: Sequence[int],
                     framing: str = "bullet") -> str:
    """Render fact texts in the given order. Presentation only; the output
    carries no identity and is never hashed for matching."""
    order = _check_permutation(order, len(facts), "order")
    lines = [facts[i].text for i in order]
    if framing == "bullet":
        return "\n".join(f"- {line}" for line in lines)
    if framing == "numbered":
        return "\n".join(f"{k + 1}. {line}" for k, line in enumerate(lines))
    if framing == "prose":
        return " ".join(line.rstrip(".") + "." for line in lines)
    raise ValueError(f"unknown framing {framing!r}")


def build_matched_fact_pair(
    facts: Sequence[Fact],
    order_a: Sequence[int],
    order_b: Sequence[int],
    variant_a: str = "order_a",
    variant_b: str = "order_b",
    framing_a: str = "bullet",
    framing_b: str = "bullet",
) -> MatchedFactPair:
    """Build the matched design: identical fact multiset, two presentations.

    Both arms share one ``semantic_fact_id``; only order/framing varies.
    A text-hash identity scheme would assign the two arms different IDs -
    exactly the failure mode this primitive replaces.
    """
    facts = list(facts)
    order_a = _check_permutation(order_a, len(facts), "order_a")
    order_b = _check_permutation(order_b, len(facts), "order_b")
    fact_set_id = semantic_fact_multiset_id(facts)
    presentation_a = RenderedPresentation(
        fact_set_id=fact_set_id,
        variant=variant_a,
        order=order_a,
        text=render_fact_list(facts, order_a, framing_a),
    )
    presentation_b = RenderedPresentation(
        fact_set_id=fact_set_id,
        variant=variant_b,
        order=order_b,
        text=render_fact_list(facts, order_b, framing_b),
    )
    return MatchedFactPair(
        semantic_fact_id=fact_set_id,
        presentation_a=presentation_a,
        presentation_b=presentation_b,
        fact_count=len(facts),
        fact_ids=tuple(fact.fact_id for fact in facts),
    )
