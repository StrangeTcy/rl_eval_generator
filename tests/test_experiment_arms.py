"""Tests for the S-line paired-arm construction primitive (Batch 7).

Source grounding: corpus shared primitive #4 (Arm / arm_seed /
build_paired_arms) and the S-line assessment user decision (option c):
offline primitive, explicitly UNUSED until model-call authorization.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.experiment_arms import (  # noqa: E402
    ARM_NAMES,
    Arm,
    arm_seed,
    build_paired_arms,
)


def test_arms_share_everything_except_the_prompt_supplement() -> None:
    """Corpus test: the matched design as data."""
    arms = build_paired_arms("inst-01", "CARD TEXT", "GENERIC TEXT")
    assert {a.name for a in arms} == {"card", "generic_advice", "none"}
    assert [a.name for a in arms] == ["card", "generic_advice", "none"]
    assert arms[0].prompt_supplement == "CARD TEXT"
    assert arms[1].prompt_supplement == "GENERIC TEXT"
    assert arms[2].prompt_supplement == ""


def test_arm_seed_is_deterministic_and_arm_specific() -> None:
    """Corpus test: reproducible, and arms must not collapse onto one seed."""
    s1 = arm_seed("inst-01", "card")
    s2 = arm_seed("inst-01", "generic_advice")
    assert s1 != s2
    assert arm_seed("inst-01", "card") == s1
    assert arm_seed("inst-01", "none") not in (s1, s2)


def test_arm_seed_is_instance_specific_and_bounded() -> None:
    card_a = arm_seed("inst-01", "card")
    card_b = arm_seed("inst-02", "card")
    assert card_a != card_b
    for instance in ("inst-01", "inst-02", "epistemic_announcements:7:3"):
        for arm in ARM_NAMES:
            value = arm_seed(instance, arm)
            assert 0 <= value < 2**31


def test_all_arm_instance_pairs_are_distinct() -> None:
    seen = set()
    for instance in (f"inst-{i:03d}" for i in range(20)):
        for arm in ARM_NAMES:
            pair = (instance, arm_seed(instance, arm))
            assert pair not in seen
            seen.add(pair)
    # No two (instance, arm) pairs collide on the seed within an instance.
    for instance in (f"inst-{i:03d}" for i in range(20)):
        seeds = [arm_seed(instance, arm) for arm in ARM_NAMES]
        assert len(set(seeds)) == len(ARM_NAMES)


def test_validation_errors() -> None:
    with pytest.raises(ValueError):
        build_paired_arms("", "card", "generic")
    with pytest.raises(ValueError):
        build_paired_arms("inst-01", "", "generic")
    with pytest.raises(ValueError):
        build_paired_arms("inst-01", "card", "")
    with pytest.raises(ValueError):
        arm_seed("", "card")
    with pytest.raises(ValueError):
        arm_seed("inst-01", "bogus_arm")


def test_primitive_is_unused_by_environments_judges_and_tools() -> None:
    """Option-c boundary: while model calls are unauthorized, no env, judge,
    renderer, or tool may consume the arm primitive (tests and the shared
    module itself are the only allowed references)."""
    offenders = []
    scan_roots = [ROOT / "envs", ROOT / "tools", ROOT / "arena", ROOT / "arena.py"]
    for root in scan_roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            if not path.is_file():
                continue
            if "experiment_arms" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(ROOT)))
    shared_dir = ROOT / "shared"
    for path in sorted(shared_dir.rglob("*.py")):
        if path.name == "experiment_arms.py":
            continue
        if "experiment_arms" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"experiment_arms consumed before authorization: {offenders}"
