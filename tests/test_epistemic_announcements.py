"""Tests for the epistemic_announcements family (Mission 02 question E2).

Covers: deterministic generation, the truncation-flip discrimination
certificate, truthful/informative announcement chains, exact ground-truth
recomputation through the accepted shared substrate (semi-independent of the
family core's own bookkeeping), the knowledge boundary of the public task,
and binary grading.
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

CORE_PATH = ROOT / "envs" / "epistemic_announcements" / "files" / "core.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("epa_core_under_test", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()

from shared.epistemic_semantics import public_announcements as PAL  # noqa: E402

WORLDS = ("three", "four")
DEPTHS = ("one", "chain")
QUERIES = ("factual", "nested")
SCENARIOS = ("expedition", "office")
SEEDS = (0, 1, 2, 3, 4, 5)


def _grid():
    return itertools.product(WORLDS, DEPTHS, QUERIES, SCENARIOS, SEEDS)


def _build(worlds, depth, query, scenario, seed):
    return CORE.build_instance(worlds=worlds, depth=depth, query=query,
                               scenario=scenario, seed=seed)


def test_full_grid_constructs_and_is_deterministic() -> None:
    cells = list(_grid())
    assert len(cells) == 96, "2 worlds x 2 depths x 2 queries x 2 scenarios x 6 seeds"
    for worlds, depth, query, scenario, seed in cells:
        first = _build(worlds, depth, query, scenario, seed)
        second = _build(worlds, depth, query, scenario, seed)
        assert first.to_spec() == second.to_spec()
        assert first.public_task_md() == second.public_task_md()


def test_truncation_flip_certificate_on_nested_instances() -> None:
    """No emitted NESTED instance may be announcement-depth invariant.

    Factual (atomic) queries are the matched control: atom truths survive
    every truthful restriction, so their classification is depth-invariant
    by design. We assert both halves of that contract.
    """
    for worlds, depth, query, scenario, seed in _grid():
        inst = _build(worlds, depth, query, scenario, seed)
        if query == "nested":
            assert len(set(inst.prefix_truths)) > 1, (
                f"non-discriminating nested instance emitted: {worlds}/{depth}/"
                f"{query}/{scenario}/{seed} prefix_truths={inst.prefix_truths}"
            )
        else:
            assert len(set(inst.prefix_truths)) == 1, (
                f"factual control must be depth-invariant: {worlds}/{depth}/"
                f"{scenario}/{seed} prefix_truths={inst.prefix_truths}"
            )


def test_announcement_structure_matches_depth_axis() -> None:
    for worlds, depth, query, scenario, seed in _grid():
        inst = _build(worlds, depth, query, scenario, seed)
        n = len(inst.announcements)
        if depth == "one":
            assert n == 1, "single-step control must realize exactly one announcement"
        else:
            # Chains realize at least two informative steps, capped by the
            # target depth and by n_worlds - 1 (each informative announcement
            # removes at least one world).
            assert 2 <= n <= min(3, CORE.WORLDS_BY_AXIS[worlds] - 1)
        assert len(inst.prefix_truths) == n + 1


def test_spec_recomputation_through_the_accepted_substrate() -> None:
    """Semi-independent check: rebuild the model straight from the spec's raw
    fields using the accepted PAL substrate (not the family's bookkeeping)
    and require the same announcements truthfulness, final worlds, and query
    truth that the spec claims."""
    for worlds, depth, query, scenario, seed in _grid():
        spec = _build(worlds, depth, query, scenario, seed).to_spec()
        world_ids = sorted(spec["valuation"])
        model = PAL.EpistemicModel(
            frozenset(world_ids),
            {agent: frozenset(frozenset(cell) for cell in cells)
             for agent, cells in spec["partitions"].items()},
            {w: frozenset(spec["valuation"][w]) for w in world_ids},
        )
        actual = spec["actual_world"]
        for struct in spec["announcements"]:
            formula = CORE._formula(tuple(struct))
            # Truthfulness at the actual world, pre-update.
            assert formula(model, actual), f"announcement {struct} not truthful"
            before = len(model.worlds)
            model = PAL.public_announce_checked(model, actual, formula)
            # Informativeness: every announcement strictly restricts.
            assert len(model.worlds) < before
        query_formula = CORE._formula(tuple(spec["query_formula"]))
        assert bool(query_formula(model, actual)) == spec["ground_truth"]
        assert sorted(model.worlds) == spec["final_worlds"]
        assert actual in spec["final_worlds"]


def test_public_task_leaks_no_ground_truth_fields() -> None:
    withheld = ("actual_world", "ground_truth", "prefix_truths", "final_worlds")
    for worlds, depth, query, scenario, seed in _grid():
        inst = _build(worlds, depth, query, scenario, seed)
        text = inst.public_task_md()
        for token in withheld:
            assert token not in text, f"{token} leaked into task.md"
        # No Python boolean literals: the task must not print truth values.
        assert "True" not in text and "False" not in text
        # The actual world must not be singled out anywhere.
        assert f"actual" not in text.lower() or "actual scenario is not revealed" in text
        assert "%%" not in text


def test_query_publicly_derivable_after_full_transcript() -> None:
    """Fairness invariant: the registered question must be settled by the
    public transcript alone - its truth is constant across every scenario
    surviving all announcements."""
    for worlds, depth, query, scenario, seed in _grid():
        spec = _build(worlds, depth, query, scenario, seed).to_spec()
        model = PAL.EpistemicModel(
            frozenset(sorted(spec["valuation"])),
            {agent: frozenset(frozenset(cell) for cell in cells)
             for agent, cells in spec["partitions"].items()},
            {w: frozenset(spec["valuation"][w]) for w in spec["valuation"]},
        )
        for step, ann in enumerate(spec["announcements"]):
            model = PAL.public_announce_checked(
                model, spec["actual_world"], CORE._formula(tuple(ann))
            )
        formula = CORE._formula(tuple(spec["query_formula"]))
        truths = {bool(formula(model, w)) for w in model.worlds}
        assert len(truths) == 1, (
            f"instance {worlds}/{depth}/{query}/{scenario}/{seed} is not "
            "publicly derivable"
        )


def test_grading_binary_exact_classification() -> None:
    inst = _build("four", "chain", "nested", "office", 0)
    gt = CORE.ground_truth_answer(inst)
    good = inst.grade(gt, 0.85)
    assert good["failure_mode"] == "pass"
    assert good["metrics"]["score"] == 1.0
    assert good["checks"]["truth_correct"] is True

    wrong = dict(gt, truth=not gt["truth"])
    bad = inst.grade(wrong, 0.85)
    assert bad["failure_mode"] == "wrong_truth"
    assert bad["metrics"]["score"] == 0.0
    assert bad["checks"]["truth_correct"] is False

    malformed = inst.grade({"truth": "yes", "justification": "x"}, 0.85)
    assert malformed["failure_mode"] == "answer_format_invalid"
    assert malformed["metrics"]["score"] == 0.0

    extra_key = inst.grade({"truth": gt["truth"], "justification": "x", "hint": 1}, 0.85)
    assert extra_key["failure_mode"] == "answer_format_invalid"


def test_query_pools_differ_by_axis() -> None:
    factual = {tuple(_build("three", "one", "factual", "office", s).query) for s in range(6)}
    nested = {tuple(_build("three", "one", "nested", "office", s).query) for s in range(6)}
    assert all(struct[0] == "atom" or struct[0] == "neg" for struct in factual)
    assert all(struct[0] in ("knows", "neg") for struct in nested)


def test_unknown_axis_values_raise_value_error() -> None:
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="five", depth="one", query="factual",
                            scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="three", depth="long", query="factual",
                            scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="three", depth="one", query="modal",
                            scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(worlds="three", depth="one", query="factual",
                            scenario="harbor", seed=0)
