"""Tests for the epistemic_nested_knowledge family (Mission 02 question E4).

Covers: deterministic generation, the first-order-indistinguishability
discrimination certificate, order-axis correctness, exact ground-truth
recomputation through the accepted shared substrate, the public-task
knowledge boundary, and binary grading.
"""
from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_PATH = ROOT / "envs" / "epistemic_nested_knowledge" / "files" / "core.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("epnk_core_under_test", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()

from shared.epistemic_semantics import public_announcements as PAL  # noqa: E402

WORLDS = ("four", "six")
ORDERS = ("first", "second", "third")
SCENARIOS = ("expedition", "office")
SEEDS = (0, 1, 2, 3, 4, 5)


def _grid():
    return itertools.product(WORLDS, ORDERS, SCENARIOS, SEEDS)


def _build(worlds, order, scenario, seed):
    return CORE.build_instance(worlds=worlds, order=order, scenario=scenario, seed=seed)


def test_full_grid_constructs_and_is_deterministic() -> None:
    cells = list(_grid())
    assert len(cells) == 72, "2 worlds x 3 orders x 2 scenarios x 6 seeds"
    for worlds, order, scenario, seed in cells:
        first = _build(worlds, order, scenario, seed)
        second = _build(worlds, order, scenario, seed)
        assert first.to_spec() == second.to_spec()
        assert first.public_task_md() == second.public_task_md()


def test_order_axis_matches_registered_formula_depth() -> None:
    expected = {"first": 1, "second": 2, "third": 3}
    for worlds, order, scenario, seed in _grid():
        spec = _build(worlds, order, scenario, seed).to_spec()
        assert spec["query_order"] == expected[order]
        assert CORE._formula_order(tuple(spec["query_formula"])) == expected[order]


def test_discrimination_certificate_on_every_instance() -> None:
    """The evaluated scenario must have a same-valuation twin at which the
    registered formula flips — otherwise the first-order facts of the named
    scenario alone decide the answer."""
    for worlds, order, scenario, seed in _grid():
        spec = _build(worlds, order, scenario, seed).to_spec()
        model = PAL.EpistemicModel(
            frozenset(sorted(spec["valuation"])),
            {agent: frozenset(frozenset(cell) for cell in cells)
             for agent, cells in spec["partitions"].items()},
            {w: frozenset(spec["valuation"][w]) for w in spec["valuation"]},
        )
        formula = CORE._formula(tuple(spec["query_formula"]))
        actual = spec["actual_world"]
        actual_truth = bool(formula(model, actual))
        twins = [
            v for v in sorted(model.worlds)
            if v != actual and set(spec["valuation"][v]) == set(spec["valuation"][actual])
        ]
        assert twins, (
            f"instance {worlds}/{order}/{scenario}/{seed}: evaluated "
            "scenario has no first-order twin"
        )
        assert any(bool(formula(model, v)) != actual_truth for v in twins), (
            f"instance {worlds}/{order}/{scenario}/{seed} is decided by "
            "first-order facts alone"
        )


def test_ground_truth_recomputation_through_the_accepted_substrate() -> None:
    for worlds, order, scenario, seed in _grid():
        spec = _build(worlds, order, scenario, seed).to_spec()
        model = PAL.EpistemicModel(
            frozenset(sorted(spec["valuation"])),
            {agent: frozenset(frozenset(cell) for cell in cells)
             for agent, cells in spec["partitions"].items()},
            {w: frozenset(spec["valuation"][w]) for w in spec["valuation"]},
        )
        formula = CORE._formula(tuple(spec["query_formula"]))
        assert bool(formula(model, spec["actual_world"])) == spec["ground_truth"]


def test_public_task_leaks_no_ground_truth_fields() -> None:
    withheld = ("actual_world", "ground_truth", "query_order")
    for worlds, order, scenario, seed in _grid():
        text = _build(worlds, order, scenario, seed).public_task_md()
        for token in withheld:
            assert token not in text, f"{token} leaked into task.md"
        assert "True" not in text and "False" not in text
        assert "%%" not in text


def test_grading_binary_exact_classification() -> None:
    inst = _build("four", "third", "office", 0)
    gt = CORE.ground_truth_answer(inst)
    good = inst.grade(gt, 1.0)
    assert good["failure_mode"] == "pass" and good["metrics"]["score"] == 1.0
    wrong = dict(gt, truth=not gt["truth"])
    bad = inst.grade(wrong, 1.0)
    assert bad["failure_mode"] == "wrong_truth" and bad["metrics"]["score"] == 0.0
    malformed = inst.grade({"truth": 1, "justification": "x"}, 1.0)
    assert malformed["failure_mode"] == "answer_format_invalid"


def test_unknown_axis_values_raise_value_error() -> None:
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="five", order="first", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="three", order="fourth", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="three", order="first", scenario="harbor", seed=0)
