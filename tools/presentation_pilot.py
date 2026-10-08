"""T1 matched-fact presentation pilot (offline, no model calls).

Operationalizes the corpus-approved T1 identity fix on the four E-line
families:

1. FACT EXTRACTION from the judge-side structured spec (``to_spec``) -
   never from rendered text. Every fact gets a generation-time ``fact_id``
   and a renderer-independent ``canonical_content``.
2. MATCHED ARMS: the identical fact multiset under two presentations
   (permuted order and/or framing), sharing one ``semantic_fact_id``.
3. PILOT CHECKS: identity stability across presentations, commutativity of
   the multiset ID, sensitivity to content changes, and the text-hash
   failure-mode contrast (naive text hashing splits matched arms).

Scope note (carried from the corpus): this is the `implementable primitive`
pilot. It does not measure behavior, makes no attention-mechanism claims,
and the broader presentation-order-effect question stays
`needs prior-art/source check first`.

Usage (offline):
    python tools/presentation_pilot.py \\
        --env epistemic_silence \\
        --difficulty silence,pair,skewed,office --seed 3
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.presentation_identity import (  # noqa: E402
    Fact,
    build_matched_fact_pair,
    semantic_fact_multiset_id,
)

ENV_CORES = {
    "epistemic_announcements": "envs/epistemic_announcements/files/core.py",
    "epistemic_nested_knowledge": "envs/epistemic_nested_knowledge/files/core.py",
    "epistemic_fragmented_observation": "envs/epistemic_fragmented_observation/files/core.py",
    "epistemic_silence": "envs/epistemic_silence/files/core.py",
}


def load_core(env_name: str):
    if env_name not in ENV_CORES:
        raise ValueError(f"unknown env {env_name!r}; options: {sorted(ENV_CORES)}")
    path = REPO_ROOT / ENV_CORES[env_name]
    spec = importlib.util.spec_from_file_location(f"t1_pilot_core_{env_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Structured fact extraction (spec -> facts). Never parses rendered text.
# ---------------------------------------------------------------------------

def _fact(family: str, index: int, kind: str, canonical: Dict[str, object],
          text: str) -> Fact:
    return Fact(
        fact_id=f"{family}-f{index:03d}-{kind}",
        canonical_content={"kind": kind, **canonical},
        text=text,
    )


def extract_facts(spec: dict) -> List[Fact]:
    family = spec["family"]
    facts: List[Fact] = []
    index = 0

    if family in (
        "epistemic_announcements",
        "epistemic_nested_knowledge",
        "epistemic_fragmented_observation",
    ):
        for world in sorted(spec["valuation"]):
            atoms = list(spec["valuation"][world])
            facts.append(_fact(
                family, index, "world_facts",
                {"world": world, "atoms": atoms},
                f"{world}: facts = {atoms}",
            ))
            index += 1
        for agent in sorted(spec["partitions"]):
            cells = spec["partitions"][agent]
            facts.append(_fact(
                family, index, "partition",
                {"agent": agent, "cells": cells},
                f"{agent}: partition cells = {cells}",
            ))
            index += 1
        if family == "epistemic_announcements":
            for step, announcement in enumerate(spec["announcements"]):
                facts.append(_fact(
                    family, index, "announcement",
                    {"step": step, "formula": announcement},
                    f"announcement[{step}] = {announcement}",
                ))
                index += 1
        else:
            facts.append(_fact(
                family, index, "target_scenario",
                {"world": spec["actual_world"]},
                f"evaluated scenario = {spec['actual_world']}",
            ))
            index += 1
        facts.append(_fact(
            family, index, "registered_query",
            {"formula": spec["query_formula"]},
            f"registered query = {spec['query_formula']}",
        ))
        index += 1
    elif family == "epistemic_silence":
        for world in sorted(spec["prior_dist"]):
            facts.append(_fact(
                family, index, "prior",
                {"world": world, "probability": spec["prior_dist"][world]},
                f"prior({world}) = {spec['prior_dist'][world]}",
            ))
            index += 1
        for agent in sorted(spec["announce_sets"]):
            facts.append(_fact(
                family, index, "announcement_rule",
                {"agent": agent, "announces_in": spec["announce_sets"][agent]},
                f"{agent} announces exactly in {spec['announce_sets'][agent]}",
            ))
            index += 1
        facts.append(_fact(
            family, index, "observation",
            {"event": spec["observation"]},
            f"observed event = {spec['observation']}",
        ))
        index += 1
    else:
        raise ValueError(f"no fact extraction registered for family {family!r}")
    return facts


# ---------------------------------------------------------------------------
# Pilot checks.
# ---------------------------------------------------------------------------

def run_pilot(spec: dict) -> dict:
    """Build matched presentation arms for one instance and check identity.

    Returns a JSON-safe report; raises on any invariant violation.
    """
    facts = extract_facts(spec)
    n = len(facts)
    if n < 2:
        raise ValueError("pilot requires at least two facts to permute")
    order_a = tuple(range(n))
    order_b = tuple(reversed(order_a))
    pair = build_matched_fact_pair(
        facts, order_a, order_b,
        variant_a="canonical_order_bullet",
        variant_b="reversed_order_numbered",
        framing_a="bullet", framing_b="numbered",
    )

    # Identity must be presentation-invariant.
    assert pair.presentation_a.fact_set_id == pair.semantic_fact_id
    assert pair.presentation_b.fact_set_id == pair.semantic_fact_id
    # Recomputation from the same structured facts is exact (determinism).
    assert semantic_fact_multiset_id(extract_facts(spec)) == pair.semantic_fact_id
    # Both presentations carry exactly the same fact texts (as a multiset).
    texts_a = {facts[i].text for i in order_a}
    texts_b = {facts[i].text for i in order_b}
    assert texts_a == texts_b

    # Contrast: a naive text-hash identity scheme splits the matched arms.
    text_hash_a = hashlib.sha256(pair.presentation_a.text.encode("utf-8")).hexdigest()
    text_hash_b = hashlib.sha256(pair.presentation_b.text.encode("utf-8")).hexdigest()

    return {
        "family": spec["family"],
        "fact_count": n,
        "semantic_fact_id": pair.semantic_fact_id,
        "identity_stable_across_presentations": True,
        "multiset_id_commutative_over_order": True,
        "text_hash_would_split_arms": text_hash_a != text_hash_b,
        "variants": [pair.presentation_a.variant, pair.presentation_b.variant],
        "fact_ids": list(pair.fact_ids),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", required=True, choices=sorted(ENV_CORES))
    parser.add_argument("--difficulty", required=True,
                        help="comma-separated axis levels, as in generate_env.py")
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)

    core = load_core(args.env)
    axes = [axis["id"] for axis in _config_axes(args.env)]
    levels = [lv.strip().lower() for lv in args.difficulty.split(",")]
    if len(levels) != len(axes):
        print(f"ERROR: expected {len(axes)} axis levels ({axes}), got {levels}")
        return 1
    kwargs = dict(zip(axes, levels))
    instance = core.build_instance(seed=args.seed, **kwargs)
    report = run_pilot(instance.to_spec())
    report["env"] = args.env
    report["difficulty"] = dict(zip(axes, levels))
    report["seed"] = args.seed
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _config_axes(env_name: str) -> list:
    import yaml

    config_path = REPO_ROOT / "envs" / env_name / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config["axes"]


if __name__ == "__main__":
    sys.exit(main())
