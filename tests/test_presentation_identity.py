"""T1 matched-fact presentation pilot tests (Batch 4).

Source grounding: corpus T1 identity fix (canonical fact IDs assigned at
generation time; identity over structured content, never rendered text) and
the paired-arm matched design (same facts, varied presentation). Offline
only: no model calls, no behavior measurement, no attention claims.

Coverage:
* primitive level: identity stability across order/framing, multiset
  commutativity, content sensitivity, text-hash failure-mode contrast,
  permutation validation;
* family level: structured fact extraction from judge-side specs for all
  four E-line families, pilot invariants, determinism, and sensitivity of
  the semantic ID to spec content changes.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.presentation_identity import (  # noqa: E402
    Fact,
    build_matched_fact_pair,
    canonical_semantic_hash,
    semantic_fact_multiset_id,
)
from tools import presentation_pilot as PILOT  # noqa: E402


def _load_core(name: str, relpath: str):
    path = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


E2 = _load_core("t1_e2_core", "envs/epistemic_announcements/files/core.py")
E4 = _load_core("t1_e4_core", "envs/epistemic_nested_knowledge/files/core.py")
E5 = _load_core("t1_e5_core", "envs/epistemic_fragmented_observation/files/core.py")
E3 = _load_core("t1_e3_core", "envs/epistemic_silence/files/core.py")


def _facts():
    return [
        Fact("f-000", {"metric": "accuracy", "value": "0.42"},
             "Accuracy was 0.42, reported first."),
        Fact("f-001", {"metric": "coverage", "value": "0.87"},
             "Coverage reached 0.87."),
        Fact("f-002", {"metric": "latency_ms", "value": "230"},
             "Median latency was 230 ms."),
    ]


def test_same_fact_different_presentation_keeps_identity_stable() -> None:
    facts = _facts()
    pair = build_matched_fact_pair(
        facts, (0, 1, 2), (2, 1, 0),
        variant_a="lead", variant_b="trail",
        framing_a="bullet", framing_b="numbered",
    )
    assert pair.presentation_a.fact_set_id == pair.semantic_fact_id
    assert pair.presentation_b.fact_set_id == pair.semantic_fact_id
    assert pair.presentation_a.text != pair.presentation_b.text
    assert pair.fact_ids == ("f-000", "f-001", "f-002")


def test_multiset_id_commutative_over_order_but_sensitive_to_content() -> None:
    facts = _facts()
    base = semantic_fact_multiset_id(facts)
    assert semantic_fact_multiset_id(list(reversed(facts))) == base
    assert semantic_fact_multiset_id([facts[1], facts[0], facts[2]]) == base
    # Any content change moves the identity.
    changed = [facts[0], facts[1],
               Fact("f-002", {"metric": "latency_ms", "value": "231"},
                    "Median latency was 231 ms.")]
    assert semantic_fact_multiset_id(changed) != base
    # fact_id changes alone do NOT move content identity...
    renamed = [Fact("z-999", dict(f.canonical_content), f.text) for f in facts]
    assert semantic_fact_multiset_id(renamed) == base
    # ...while canonical_semantic_hash is per-fact content identity.
    assert canonical_semantic_hash(facts[0]) == canonical_semantic_hash(renamed[0])
    assert canonical_semantic_hash(facts[0]) != canonical_semantic_hash(changed[2])


def test_text_hash_would_have_broken_matching_demo() -> None:
    """The exact failure mode the corpus flags: hashing rendered text
    assigns matched presentations DIFFERENT identities."""
    facts = _facts()
    pair = build_matched_fact_pair(facts, (0, 1, 2), (2, 1, 0))
    hash_a = hashlib.sha256(pair.presentation_a.text.encode()).hexdigest()
    hash_b = hashlib.sha256(pair.presentation_b.text.encode()).hexdigest()
    assert hash_a != hash_b, "text hash must split the matched arms"
    assert pair.semantic_fact_id == semantic_fact_multiset_id(facts)


def test_orders_must_be_permutations() -> None:
    facts = _facts()
    with pytest.raises(ValueError):
        build_matched_fact_pair(facts, (0, 1, 1), (0, 1, 2))
    with pytest.raises(ValueError):
        build_matched_fact_pair(facts, (0, 1), (0, 1, 2))
    with pytest.raises(ValueError):
        build_matched_fact_pair(facts, (0, 1, 2), (3, 1, 0))


INSTANCES = [
    ("epistemic_announcements",
     lambda s: E2.build_instance(worlds="three", depth="chain", query="nested",
                                 scenario="office", seed=s)),
    ("epistemic_announcements",
     lambda s: E2.build_instance(worlds="four", depth="one", query="factual",
                                 scenario="expedition", seed=s)),
    ("epistemic_nested_knowledge",
     lambda s: E4.build_instance(worlds="six", order="third",
                                 scenario="expedition", seed=s)),
    ("epistemic_fragmented_observation",
     lambda s: E5.build_instance(worlds="four", fragment="asymmetric",
                                 scenario="office", seed=s)),
    ("epistemic_fragmented_observation",
     lambda s: E5.build_instance(worlds="six", fragment="symmetric",
                                 scenario="expedition", seed=s)),
    ("epistemic_silence",
     lambda s: E3.build_instance(observation="silence", protocol="pair",
                                 prior="uniform", scenario="office", seed=s)),
    ("epistemic_silence",
     lambda s: E3.build_instance(observation="message", protocol="single",
                                 prior="skewed", scenario="expedition", seed=s)),
]


def test_fact_extraction_is_structured_and_nonempty() -> None:
    for family, make in INSTANCES:
        spec = make(0).to_spec()
        facts = PILOT.extract_facts(spec)
        assert facts, f"no facts extracted for {family}"
        # Generation-time identity: every fact carries an id assigned before
        # any rendering, and canonical content never references rendered text.
        seen = set()
        for fact in facts:
            assert fact.fact_id not in seen
            seen.add(fact.fact_id)
            assert isinstance(fact.canonical_content, dict)
            assert fact.canonical_content.get("kind")


def test_pilot_identity_invariants_on_all_families() -> None:
    for family, make in INSTANCES:
        for seed in (0, 1):
            spec = make(seed).to_spec()
            report = PILOT.run_pilot(spec)
            assert report["family"] == family
            assert report["identity_stable_across_presentations"]
            assert report["multiset_id_commutative_over_order"]
            assert report["text_hash_would_split_arms"]
            assert report["fact_count"] >= 2
            # Determinism: the same spec always yields the same identity.
            assert PILOT.run_pilot(spec)["semantic_fact_id"] == \
                report["semantic_fact_id"]


def test_semantic_id_sensitive_to_spec_content_changes() -> None:
    spec = E3.build_instance(observation="silence", protocol="pair",
                             prior="uniform", scenario="office", seed=1).to_spec()
    base = PILOT.run_pilot(spec)["semantic_fact_id"]
    mutated = copy.deepcopy(spec)
    mutated["prior_dist"]["w1"] = "1/2"
    mutated["prior_dist"]["w2"] = "1/4"
    assert PILOT.run_pilot(mutated)["semantic_fact_id"] != base

    spec2 = E2.build_instance(worlds="three", depth="one", query="nested",
                              scenario="office", seed=1).to_spec()
    base2 = PILOT.run_pilot(spec2)["semantic_fact_id"]
    mutated2 = copy.deepcopy(spec2)
    world = sorted(mutated2["valuation"])[0]
    atoms = mutated2["valuation"][world]
    mutated2["valuation"][world] = (
        ["q"] if atoms == ["p"] else ["p"]
    )
    assert PILOT.run_pilot(mutated2)["semantic_fact_id"] != base2
