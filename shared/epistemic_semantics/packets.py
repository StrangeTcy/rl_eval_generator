"""Closed public-packet schemas with a ground-truth forbid-list (V1 layer).

Source grounding: final review round of ``mission-02/code snippets critique.md``
(fable-5, shared-primitive "closed public-packet schema + GT forbid-list" and
the ``packets.py`` block: "closed schema, REQUIRED/FORBIDDEN,
render_injectivity_probe") and the V1 question (English rendering must contain
exactly the registered public information — no more, no less).

A *packet* is the public, learner-visible projection of one instance. The
schema is closed: unknown keys are rejected as loudly as missing ones, and any
key on the ground-truth forbid-list must never appear in a public packet —
hidden state, answer keys, and privileged metadata stay judge-side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Mapping, Sequence, Tuple

from .event_bayes import SpecError, require

__all__ = ["PacketSchema", "validate_packet", "render_injectivity_probe"]


@dataclass(frozen=True)
class PacketSchema:
    """Closed schema for one packet kind.

    ``required`` keys must be present; ``optional`` keys may be present;
    any other key is a violation (closed schema). ``forbidden`` names the
    ground-truth / privileged keys that must never be present even if they
    would otherwise look optional — kept separate from ``optional`` so a
    future edit cannot silently legalize them.
    """

    kind: str
    required: FrozenSet[str]
    optional: FrozenSet[str] = field(default_factory=frozenset)
    forbidden: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        require(bool(self.kind), "packet kind must be named")
        overlap = (self.required & self.optional) | \
            ((self.required | self.optional) & self.forbidden)
        require(not overlap, f"schema sets overlap: {sorted(overlap)}")

    @property
    def allowed(self) -> FrozenSet[str]:
        return self.required | self.optional


def validate_packet(packet: Mapping[str, object], schema: PacketSchema) -> None:
    """Raise ``SpecError`` unless ``packet`` conforms to the closed schema."""
    if not isinstance(packet, Mapping):
        raise SpecError(f"{schema.kind}: packet must be a mapping")
    keys = set(packet)
    missing = schema.required - keys
    if missing:
        raise SpecError(f"{schema.kind}: missing required keys {sorted(missing)}")
    leaked = keys & schema.forbidden
    if leaked:
        raise SpecError(f"{schema.kind}: forbidden ground-truth keys {sorted(leaked)}")
    unknown = keys - schema.allowed
    if unknown:
        raise SpecError(f"{schema.kind}: unknown keys {sorted(unknown)} (closed schema)")


def render_injectivity_probe(
    rendered: Sequence[Tuple[str, Mapping[str, object]]],
    schema: PacketSchema,
) -> Dict[str, object]:
    """V1 probe over a batch of rendered packets.

    Checks, per packet: closed-schema validity and absence of forbidden keys.
    Checks, across the batch: no two distinct instance ids render to identical
    packets (an injectivity collision means the rendering cannot distinguish
    instances the formal spec distinguishes — a fidelity failure, since a
    reader could not reconstruct which instance they are answering).

    Returns a report dict; raises nothing on collisions so callers can decide
    the disposition, but raises ``SpecError`` for schema violations (those are
    construction bugs, not findings).
    """
    seen: Dict[str, list] = {}
    collisions = []
    for instance_id, packet in rendered:
        validate_packet(packet, schema)
        key = repr(sorted((k, repr(v)) for k, v in packet.items()))
        if key in seen and instance_id not in seen[key]:
            collisions.append({"instance_id": instance_id, "matches": seen[key][:]})
        seen.setdefault(key, []).append(instance_id)
    return {
        "kind": schema.kind,
        "packets": len(rendered),
        "distinct_packets": len(seen),
        "injective": not collisions,
        "collisions": collisions,
    }
