"""Differential guard for the D2 refactor of envs/epistemic_games.

The v0 core was refactored to take its exact posterior and likelihood-ratio
verdict band from shared/epistemic_semantics/bayes.py (single source of
truth, user-approved 2026-10-07). The fixture
``fixtures/v0_differential.jsonl`` was captured from the PRE-refactor core
over all 48 axis cells x seeds 0..2 (144 instances) and pins, per instance:

* the rendered public task.md (byte-exact),
* the judge-side spec ``to_spec()`` (byte-exact, incl. exact-posterior string),
* grading of the ground-truth answer and three fixed wrong/bad answers
  (checks, metrics, failure mode, notes).

Any behavioral drift — different Fractions, band boundaries, taxonomy
ordering, or rendered text — fails here. Regenerate the fixture only with
explicit authorization (epistemic_program/capture_v0_fixtures.py documents
the pre-refactor capture).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE_PATH = ROOT / "envs" / "epistemic_games" / "files" / "core.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v0_differential.jsonl"


def _load_core():
    spec = importlib.util.spec_from_file_location("epg_differential_core", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()


def _records():
    with FIXTURE.open(encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def test_fixture_covers_the_full_axis_grid() -> None:
    records = list(_records())
    assert len(records) == 144, "48 axis cells x 3 seeds"
    cells = {tuple(r["axes"][:5]) for r in records}
    assert len(cells) == 48


@pytest.mark.parametrize("index", range(144))
def test_instance_behavior_is_byte_identical(index: int) -> None:
    record = list(_records())[index]
    template, evidence, presentation, prior_id, framing, seed = record["axes"]
    instance = CORE.build_instance(
        template=template,
        evidence=evidence,
        prior_id=prior_id,
        presentation=presentation,
        framing=framing,
        seed=seed,
    )
    assert instance.public_task_md() == record["task_md"]
    assert json.dumps(instance.to_spec(), sort_keys=True) == json.dumps(
        record["spec"], sort_keys=True
    )
    for key, answer in (
        ("grade_gt", CORE.ground_truth_answer(instance)),
        ("grade_wrong_a", {"posterior_world1": 0.5, "verdict": "indistinguishable",
                           "most_supported": "neither", "justification": "no information"}),
        ("grade_wrong_b", {"posterior_world1": 0.9, "verdict": "distinguishable",
                           "most_supported": "world1", "justification": "sounds genuine"}),
        ("grade_bad", {"posterior_world1": "high"}),
    ):
        got = instance.grade(answer, 0.85)
        assert json.dumps(got, sort_keys=True) == json.dumps(record[key], sort_keys=True), key


def test_shared_core_is_the_refactored_source_of_truth() -> None:
    """The verdict bands and ratio must resolve to the shared module."""
    from fractions import Fraction

    from shared.epistemic_semantics import bayes

    assert CORE.VERDICTS == bayes.VERDICTS
    assert CORE.WEAK_STRONG_RATIO == bayes.WEAK_STRONG_RATIO
    # Perfect evidence still collapses the distribution exactly.
    assert CORE._semantics_bayes.posterior_world1(
        Fraction(1, 2), Fraction(1), Fraction(0)
    ) == Fraction(1)
