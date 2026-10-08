"""CS020 S1 source-test behaviors for paired arms and run seeds.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 20 (lines 892-905).
This is a distinct tests-only block; no semantic implementation is added here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

paired_arms = importlib.import_module("experiments.paired_arms")
arm_seed = paired_arms.arm_seed
build_paired_arms = paired_arms.build_paired_arms


def test_s1_conditions_are_paired_on_one_instance_with_a_blank_control():
    arms = build_paired_arms("study-pair-39", "CARD", "GENERIC METHOD")

    assert {arm.name for arm in arms} == {"card", "generic_advice", "none"}
    assert {arm.instance_id for arm in arms} == {"study-pair-39"}
    assert arms[2].prompt_supplement == ""


def test_s1_run_seeds_repeat_per_arm_and_differ_between_arms():
    card_seed = arm_seed("study-pair-39", "card")
    advice_seed = arm_seed("study-pair-39", "generic_advice")

    assert card_seed != advice_seed
    assert arm_seed("study-pair-39", "card") == card_seed
