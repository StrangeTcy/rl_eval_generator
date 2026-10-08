"""CS019 S1 implementation checks for paired, caller-specified arms.

Source: mission-02/code snippets critique.md at pinned revision
cdd03a2365174250d32b89d970be85bae21c7998, Python block 19 (lines 868-890).
CS020's separate source-test block is not counted as covered here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

paired_arms = importlib.import_module("experiments.paired_arms")
Arm = paired_arms.Arm
arm_seed = paired_arms.arm_seed
build_paired_arms = paired_arms.build_paired_arms


def test_arm_builder_keeps_supplied_text_and_pair_identity_without_defaults():
    arms = build_paired_arms(
        "frozen-instance-24",
        "  exact card wording  ",
        "explicitly supplied generic method wording",
    )

    assert tuple(arm.name for arm in arms) == ("card", "generic_advice", "none")
    assert {arm.instance_id for arm in arms} == {"frozen-instance-24"}
    assert arms[0].prompt_supplement == "  exact card wording  "
    assert arms[1].prompt_supplement == "explicitly supplied generic method wording"
    assert arms[2].prompt_supplement == ""
    with pytest.raises(TypeError):
        build_paired_arms("frozen-instance-24", "card only")


def test_arm_specific_run_seeds_are_stable_and_do_not_replace_instance_identity():
    arms = build_paired_arms("frozen-instance-24", "card", "generic")
    run_seeds = [arm_seed(arm.instance_id, arm.name) for arm in arms]

    assert run_seeds == [arm_seed("frozen-instance-24", arm.name) for arm in arms]
    assert len(set(run_seeds)) == len(arms)
    with pytest.raises(ValueError, match="unknown S1 arm"):
        arm_seed("frozen-instance-24", "unregistered")
    with pytest.raises(ValueError, match="no-advice arm"):
        Arm("frozen-instance-24", "none", "not empty")
