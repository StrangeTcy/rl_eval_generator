#!/usr/bin/env python3
"""Capture v0 epistemic_games behavior as a differential fixture.

Run BEFORE refactoring envs/epistemic_games/files/core.py onto the shared
semantics core. After the refactor, tests/epistemic_semantics/
test_v0_differential.py regenerates every record and requires byte-identical
task.md, spec, and grading outputs.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path

FILES = Path("envs/epistemic_games/files")
spec = importlib.util.spec_from_file_location("v0_core_pre_refactor", FILES / "core.py")
import sys
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)

TEMPLATES = ("trap", "report")
EVIDENCE = ("ambiguous", "weak", "strong")
PRESENTATIONS = ("solo", "paired")
PRIORS = ("balanced", "skewed")
FRAMINGS = ("narrative", "bare_table")
SEEDS = (0, 1, 2)

WRONG_A = {"posterior_world1": 0.5, "verdict": "indistinguishable",
           "most_supported": "neither", "justification": "no information"}
WRONG_B = {"posterior_world1": 0.9, "verdict": "distinguishable",
           "most_supported": "world1", "justification": "sounds genuine"}
BAD = {"posterior_world1": "high"}

out = Path("tests/epistemic_semantics/fixtures/v0_differential.jsonl")
n = 0
with out.open("w", encoding="utf-8") as fh:
    for template, evidence, presentation, prior_id, framing in itertools.product(
            TEMPLATES, EVIDENCE, PRESENTATIONS, PRIORS, FRAMINGS):
        for seed in SEEDS:
            inst = core.build_instance(template=template, evidence=evidence,
                                       prior_id=prior_id, presentation=presentation,
                                       framing=framing, seed=seed)
            record = {
                "axes": [template, evidence, presentation, prior_id, framing, seed],
                "task_md": inst.public_task_md(),
                "spec": inst.to_spec(),
                "grade_gt": inst.grade(core.ground_truth_answer(inst), 0.85),
                "grade_wrong_a": inst.grade(WRONG_A, 0.85),
                "grade_wrong_b": inst.grade(WRONG_B, 0.85),
                "grade_bad": inst.grade(BAD, 0.85),
            }
            fh.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            n += 1
print(f"captured {n} instances -> {out}")
