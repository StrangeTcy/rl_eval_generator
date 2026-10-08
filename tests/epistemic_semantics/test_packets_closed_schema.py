"""Closed-schema packet tests (V1 layer) per the blueprint's packets block.

Named checks: "unknown + forbidden keys rejected", plus the injectivity probe
that catches two distinct instances rendering to an identical public packet.
"""
from __future__ import annotations

import pytest

from shared.epistemic_semantics.event_bayes import SpecError
from shared.epistemic_semantics.packets import (
    PacketSchema,
    render_injectivity_probe,
    validate_packet,
)

SCHEMA = PacketSchema(
    kind="two_world_instance",
    required=frozenset({"prior_world1", "policies", "observation"}),
    optional=frozenset({"template"}),
    forbidden=frozenset({"actual_world", "posterior_world1", "verdict"}),
)


def test_valid_packet_passes() -> None:
    validate_packet(
        {"prior_world1": "1/2", "policies": {}, "observation": "denial",
         "template": "trap"},
        SCHEMA,
    )


def test_unknown_keys_are_rejected_closed_schema() -> None:
    with pytest.raises(SpecError, match="unknown keys"):
        validate_packet(
            {"prior_world1": "1/2", "policies": {}, "observation": "o",
             "surprise": 1},
            SCHEMA,
        )


def test_missing_required_keys_are_rejected() -> None:
    with pytest.raises(SpecError, match="missing required"):
        validate_packet({"prior_world1": "1/2"}, SCHEMA)


def test_forbidden_ground_truth_keys_are_rejected() -> None:
    with pytest.raises(SpecError, match="forbidden"):
        validate_packet(
            {"prior_world1": "1/2", "policies": {}, "observation": "o",
             "actual_world": "world1"},
            SCHEMA,
        )
    # The answer key itself is privileged metadata.
    with pytest.raises(SpecError, match="forbidden"):
        validate_packet(
            {"prior_world1": "1/2", "policies": {}, "observation": "o",
             "verdict": "distinguishable"},
            SCHEMA,
        )


def test_schema_construction_rejects_overlaps() -> None:
    with pytest.raises(SpecError, match="overlap"):
        PacketSchema(kind="bad", required=frozenset({"a"}),
                     forbidden=frozenset({"a"}))


def test_injectivity_probe_flags_collisions() -> None:
    packet = {"prior_world1": "1/2", "policies": {}, "observation": "o"}
    report = render_injectivity_probe(
        [("i1", dict(packet)), ("i2", dict(packet)),
         ("i3", {**packet, "observation": "v"})],
        SCHEMA,
    )
    assert report["injective"] is False
    assert report["packets"] == 3 and report["distinct_packets"] == 2
    assert report["collisions"][0]["instance_id"] == "i2"
    assert report["collisions"][0]["matches"] == ["i1"]


def test_injectivity_probe_passes_on_distinct_renderings() -> None:
    base = {"prior_world1": "1/2", "policies": {}, "observation": "o"}
    report = render_injectivity_probe(
        [("i1", dict(base)), ("i2", {**base, "observation": "v"})], SCHEMA
    )
    assert report["injective"] is True and report["collisions"] == []


def test_probe_raises_on_schema_violation() -> None:
    with pytest.raises(SpecError):
        render_injectivity_probe(
            [("i1", {"prior_world1": "1/2", "actual_world": "world1"})], SCHEMA
        )
