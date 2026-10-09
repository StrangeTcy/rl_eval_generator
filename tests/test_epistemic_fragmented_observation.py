"""Tests for the epistemic_fragmented_observation family (Mission 02 question E5).

Covers: deterministic generation, the per-axis discrimination certificates
(asymmetric: pooling strictly informative; symmetric: named-scenario facts do
not decide the payload), exact ground-truth recomputation through the
accepted shared substrate (CS005 + CS011), the public-task knowledge
boundary, and binary grading.
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

CORE_PATH = ROOT / "envs" / "epistemic_fragmented_observation" / "files" / "core.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("epfo_core_under_test", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()

from shared.epistemic_semantics import fragmented_observation as CSO  # noqa: E402
from shared.epistemic_semantics import public_announcements as PAL  # noqa: E402

WORLDS = ("four", "six")
FRAGMENTS = ("symmetric", "asymmetric")
SCENARIOS = ("expedition", "office")
SEEDS = (0, 1, 2, 3, 4, 5)


def _grid():
    return itertools.product(WORLDS, FRAGMENTS, SCENARIOS, SEEDS)


def _build(worlds, fragment, scenario, seed):
    return CORE.build_instance(worlds=worlds, fragment=fragment, scenario=scenario, seed=seed)


def _model_from_spec(spec):
    return PAL.EpistemicModel(
        frozenset(sorted(spec["valuation"])),
        {agent: frozenset(frozenset(cell) for cell in cells)
         for agent, cells in spec["partitions"].items()},
        {w: frozenset(spec["valuation"][w]) for w in spec["valuation"]},
    )


def test_full_grid_constructs_and_is_deterministic() -> None:
    cells = list(_grid())
    assert len(cells) == 48, "2 worlds x 2 fragments x 2 scenarios x 6 seeds"
    for worlds, fragment, scenario, seed in cells:
        first = _build(worlds, fragment, scenario, seed)
        second = _build(worlds, fragment, scenario, seed)
        assert first.to_spec() == second.to_spec()
        assert first.public_task_md() == second.public_task_md()


def test_axis_structure() -> None:
    for worlds, fragment, scenario, seed in _grid():
        spec = _build(worlds, fragment, scenario, seed).to_spec()
        assert spec["n_worlds"] == CORE.WORLDS_BY_AXIS[worlds]
        if fragment == "symmetric":
            assert spec["partitions"]["a"] == spec["partitions"]["b"]
        else:
            assert spec["partitions"]["a"] != spec["partitions"]["b"]


def test_certificates_on_every_instance() -> None:
    for worlds, fragment, scenario, seed in _grid():
        spec = _build(worlds, fragment, scenario, seed).to_spec()
        model = _model_from_spec(spec)
        actual = spec["actual_world"]
        joint = CSO.joint_information(model, list(CORE.AGENTS), actual)
        query = tuple(spec["query_formula"])
        if fragment == "asymmetric":
            for agent in CORE.AGENTS:
                cell = model.agent_class(agent, actual)
                assert joint < cell, (
                    f"{worlds}/{fragment}/{scenario}/{seed}: pooling is not "
                    f"strictly informative for {agent}"
                )
        else:
            payload = query[1] if query[0] == "neg" else query
            formula = CORE._formula(payload)
            target_truth = bool(formula(model, actual))
            assert len(joint) >= 2
            assert any(bool(formula(model, w)) != target_truth for w in joint), (
                f"{worlds}/{fragment}/{scenario}/{seed}: named scenario "
                "facts decide the proposition alone"
            )


def test_ground_truth_recomputation_through_the_accepted_substrate() -> None:
    for worlds, fragment, scenario, seed in _grid():
        spec = _build(worlds, fragment, scenario, seed).to_spec()
        model = _model_from_spec(spec)
        actual = spec["actual_world"]
        query = tuple(spec["query_formula"])
        payload = query[1] if query[0] == "neg" else query
        formula = CORE._formula(payload)
        joint = CSO.joint_information(model, list(CORE.AGENTS), actual)
        expected = all(bool(formula(model, w)) for w in sorted(joint))
        if query[0] == "neg":
            expected = not expected
        assert expected == spec["ground_truth"]


def test_public_task_leaks_no_ground_truth_fields() -> None:
    withheld = ("ground_truth", "joint_size")
    for worlds, fragment, scenario, seed in _grid():
        text = _build(worlds, fragment, scenario, seed).public_task_md()
        for token in withheld:
            assert token not in text, f"{token} leaked into task.md"
        assert "True" not in text and "False" not in text
        assert "%%" not in text


def test_grading_binary_exact_classification() -> None:
    inst = _build("six", "asymmetric", "office", 0)
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
        CORE.build_instance(worlds="five", fragment="symmetric", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="four", fragment="fractured", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="four", fragment="symmetric", scenario="harbor", seed=0)
