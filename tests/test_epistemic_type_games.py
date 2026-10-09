"""Tests for the epistemic_type_games family (Mission 02 question E6).

Covers: independent oracle checks on hand-built games with known solution
sets (the formal solution/oracle check the portfolio requires for E6),
deterministic generation, uniqueness + partition-sensitivity certificates,
ground-truth recomputation through the enumerator, the public-task
knowledge boundary, and binary grading.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_PATH = ROOT / "envs" / "epistemic_type_games" / "files" / "core.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("eptg_core_under_test", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()

TYPES = ("small", "large")
PAYOFFS = ("mild", "sharp")
SCENARIOS = ("expedition", "office")
SEEDS = (0, 1, 2, 3, 4, 5)


def _grid():
    return itertools.product(TYPES, PAYOFFS, SCENARIOS, SEEDS)


def _build(types, payoffs, scenario, seed):
    return CORE.build_instance(types=types, payoffs=payoffs, scenario=scenario, seed=seed)


def _normal_form_game(matrix):
    """Single-type normal form: u[(aa, ab)] = (u_a, u_b)."""
    prior = {("t1", "t1"): Fraction(1)}
    payoffs = {("t1", "t1"): matrix}
    return ["t1"], ["t1"], prior, payoffs


def test_oracle_matching_pennies_has_no_pure_equilibrium() -> None:
    matrix = {
        ("X", "X"): (Fraction(1), Fraction(-1)),
        ("X", "Y"): (Fraction(-1), Fraction(1)),
        ("Y", "X"): (Fraction(-1), Fraction(1)),
        ("Y", "Y"): (Fraction(1), Fraction(-1)),
    }
    ta, tb, prior, payoffs = _normal_form_game(matrix)
    assert CORE.enumerate_pure_bne(ta, tb, prior, payoffs) == []


def test_oracle_coordination_game_has_two_pure_equilibria() -> None:
    zero = Fraction(0)
    matrix = {
        ("X", "X"): (Fraction(1), Fraction(1)),
        ("X", "Y"): (zero, zero),
        ("Y", "X"): (zero, zero),
        ("Y", "Y"): (Fraction(1), Fraction(1)),
    }
    ta, tb, prior, payoffs = _normal_form_game(matrix)
    equilibria = CORE.enumerate_pure_bne(ta, tb, prior, payoffs)
    strategies = {(e["player_a"]["t1"], e["player_b"]["t1"]) for e in equilibria}
    assert strategies == {("X", "X"), ("Y", "Y")}


def test_oracle_dominance_solvable_game_has_unique_equilibrium() -> None:
    matrix = {
        ("X", "X"): (Fraction(0), Fraction(0)),
        ("X", "Y"): (Fraction(-1), Fraction(3)),
        ("Y", "X"): (Fraction(3), Fraction(-1)),
        ("Y", "Y"): (Fraction(1), Fraction(1)),
    }
    ta, tb, prior, payoffs = _normal_form_game(matrix)
    equilibria = CORE.enumerate_pure_bne(ta, tb, prior, payoffs)
    assert len(equilibria) == 1
    assert equilibria[0]["player_a"] == {"t1": "Y"}
    assert equilibria[0]["player_b"] == {"t1": "Y"}


def test_full_grid_constructs_and_is_deterministic() -> None:
    cells = list(_grid())
    assert len(cells) == 48, "2 types x 2 payoffs x 2 scenarios x 6 seeds"
    for types, payoffs, scenario, seed in cells:
        first = _build(types, payoffs, scenario, seed)
        second = _build(types, payoffs, scenario, seed)
        assert first.to_spec() == second.to_spec()
        assert first.public_task_md() == second.public_task_md()


def test_certificates_on_every_instance() -> None:
    for types, payoffs, scenario, seed in _grid():
        inst = _build(types, payoffs, scenario, seed)
        equilibria = CORE.enumerate_pure_bne(
            inst.types_a, inst.types_b,
            inst.reconstructed_prior(), inst.reconstructed_payoffs(),
        )
        assert len(equilibria) == 1, (
            f"{types}/{payoffs}/{scenario}/{seed}: uniqueness certificate "
            f"violated ({len(equilibria)} equilibria)"
        )
        eq = equilibria[0]
        assert eq == inst.equilibrium
        varies = (
            len(set(eq["player_a"].values())) > 1
            or len(set(eq["player_b"].values())) > 1
        )
        assert varies, (
            f"{types}/{payoffs}/{scenario}/{seed}: partition-sensitivity "
            "certificate violated (constant strategies)"
        )
        assert set(inst.types_a) == set(eq["player_a"])
        assert set(inst.types_b) == set(eq["player_b"])


def test_prior_is_full_support_and_normalized() -> None:
    for types, payoffs, scenario, seed in _grid():
        inst = _build(types, payoffs, scenario, seed)
        prior = inst.reconstructed_prior()
        assert all(v > 0 for v in prior.values())
        assert sum(prior.values()) == Fraction(1)


def test_public_task_leaks_no_ground_truth_fields() -> None:
    for types, payoffs, scenario, seed in _grid():
        inst = _build(types, payoffs, scenario, seed)
        text = inst.public_task_md()
        for token in ("ground_truth", "equilibrium_correct", "strict_correct"):
            assert token not in text, f"{token} leaked into task.md"
        # The equilibrium mapping itself must not appear in any serialization.
        assert json.dumps(inst.equilibrium, sort_keys=True) not in text
        assert json.dumps(inst.equilibrium) not in text
        assert "%%" not in text


def test_grading_binary_exact_classification() -> None:
    inst = _build("small", "sharp", "office", 0)
    gt = CORE.ground_truth_answer(inst)
    good = inst.grade(gt, 1.0)
    assert good["failure_mode"] == "pass" and good["metrics"]["score"] == 1.0
    wrong = {
        "player_a": {t: ("Y" if a == "X" else "X")
                     for t, a in inst.equilibrium["player_a"].items()},
        "player_b": dict(inst.equilibrium["player_b"]),
        "justification": "x",
    }
    bad = inst.grade(wrong, 1.0)
    assert bad["failure_mode"] == "wrong_equilibrium"
    assert bad["metrics"]["score"] == 0.0
    malformed = inst.grade({"player_a": {"t1": "Z"}, "player_b": None,
                            "justification": "x"}, 1.0)
    assert malformed["failure_mode"] == "answer_format_invalid"


def test_unknown_axis_values_raise_value_error() -> None:
    with pytest.raises(ValueError):
        CORE.build_instance(types="huge", payoffs="mild", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(types="small", payoffs="extreme", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(types="small", payoffs="mild", scenario="harbor", seed=0)
