"""Deterministic semantic-preserving surface transformations."""
from __future__ import annotations

import random

from .schema import SurfaceMapping


def make_mapping(relabeling: str, seed: int = 0) -> SurfaceMapping:
    rng = random.Random(seed)
    if relabeling in {"canonical", "format_only"}:
        templates = {"A": "A", "B": "B", "C": "C"}
        payloads = {0: "0", 1: "1"}
    elif relabeling == "permuted_templates":
        names = ["Kestrel", "Mallow", "Orchid"]
        rng.shuffle(names)
        templates = dict(zip(("A", "B", "C"), names, strict=True))
        payloads = {0: "0", 1: "1"}
    elif relabeling == "recoded_payloads":
        values = ["red", "blue"]
        rng.shuffle(values)
        templates = {"A": "A", "B": "B", "C": "C"}
        payloads = {0: values[0], 1: values[1]}
    elif relabeling == "alpha_renamed":
        names = ["X", "Y", "Z"]
        rng.shuffle(names)
        templates = dict(zip(("A", "B", "C"), names, strict=True))
        payloads = {0: "zero", 1: "one"}
    else:
        raise ValueError(f"unknown relabeling: {relabeling}")
    return SurfaceMapping(templates=templates, payloads=payloads, relabeling=relabeling)
