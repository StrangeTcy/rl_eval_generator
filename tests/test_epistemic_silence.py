"""Tests for the epistemic_silence family (Mission 02 question E3).

Covers: deterministic generation, the informative-event certificate, exact
ground-truth recomputation through the accepted shared substrate (CS007
silence + CS008 supplied-policy Bayes), the public-task knowledge boundary,
binary grading, and the silence/message matched contrast.
"""
from __future__ import annotations

import importlib.util
import itertools
import re
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_PATH = ROOT / "envs" / "epistemic_silence" / "files" / "core.py"


def _load_core():
    spec = importlib.util.spec_from_file_location("eps_core_under_test", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = _load_core()

from shared.epistemic_semantics import silence as SILENCE  # noqa: E402
from shared.epistemic_semantics import supplied_policy as POLICY  # noqa: E402

OBSERVATIONS = ("silence", "message")
PROTOCOLS = ("single", "pair")
PRIORS = ("uniform", "skewed")
SCENARIOS = ("expedition", "office")
SEEDS = (0, 1, 2, 3, 4, 5)


def _grid():
    return itertools.product(OBSERVATIONS, PROTOCOLS, PRIORS, SCENARIOS, SEEDS)


def _build(observation, protocol, prior, scenario, seed):
    return CORE.build_instance(
        observation=observation, protocol=protocol, prior=prior,
        scenario=scenario, seed=seed,
    )


def _posterior_via_substrate(spec):
    prior = {w: Fraction(v) for w, v in spec["prior_dist"].items()}
    protocol = {}
    for agent, announce_set in spec["announce_sets"].items():
        members = frozenset(announce_set)
        protocol[agent] = (lambda world, _m=members: world in _m)
    table = {}
    for world in prior:
        lam = SILENCE.silence_event_likelihood(world, protocol)
        table[world] = {"silence": lam, "announcement": Fraction(1) - lam}
    realized = "silence" if spec["observation"] == "silence" else "announcement"
    inst = POLICY.SuppliedPolicyInstance(
        prior=prior, policy=table, realized_observation=realized
    )
    return POLICY.bayes_update(inst)


def test_full_grid_constructs_and_is_deterministic() -> None:
    cells = list(_grid())
    assert len(cells) == 96, "2 obs x 2 protocols x 2 priors x 2 scenarios x 6 seeds"
    for cell in cells:
        first = _build(*cell)
        second = _build(*cell)
        assert first.to_spec() == second.to_spec()
        assert first.public_task_md() == second.public_task_md()


def test_informative_event_certificate_on_every_instance() -> None:
    """The realized event must have intermediate mass and move the posterior."""
    for cell in _grid():
        spec = _build(*cell).to_spec()
        prior_w1 = Fraction(spec["prior_world1"])
        posterior_w1 = Fraction(spec["posterior_world1"])
        assert posterior_w1 != prior_w1, f"non-discriminating instance {cell}"
        assert spec["direction"] == (
            "increased" if posterior_w1 > prior_w1 else "decreased"
        )


def test_ground_truth_recomputation_through_the_accepted_substrate() -> None:
    for cell in _grid():
        spec = _build(*cell).to_spec()
        posterior = _posterior_via_substrate(spec)
        assert posterior[CORE.WORLD1] == Fraction(spec["posterior_world1"]), cell


def test_matched_counter_observation_recorded() -> None:
    """Specs carry the counter-factual matched posterior for research use."""
    for cell in _grid():
        spec = _build(*cell).to_spec()
        counter = dict(spec, observation=(
            "message" if spec["observation"] == "silence" else "silence"
        ))
        posterior = _posterior_via_substrate(counter)
        assert posterior[CORE.WORLD1] == Fraction(spec["counter_posterior_world1"]), cell


def test_public_task_leaks_no_ground_truth_fields() -> None:
    # Note: `posterior_world1` itself names the public answer field and must
    # appear in the answer protocol; it is not a secret.
    withheld = ("direction_correct", "ground_truth", "announce_sets")
    for cell in _grid():
        inst = _build(*cell)
        text = inst.public_task_md()
        for token in withheld:
            assert token not in text, f"{token} leaked into task.md"
        # The exact posterior value must not appear in the public task
        # (word-bounded, so "= 1" does not match the prior's "= 1/3").
        assert not re.search(
            r"= " + re.escape(str(inst.posterior_world1)) + r"(?![0-9/])", text
        )
        assert "%%" not in text


def test_grading_binary_exact_classification() -> None:
    inst = _build("silence", "pair", "uniform", "office", 0)
    gt = CORE.ground_truth_answer(inst)
    good = inst.grade(gt, 1.0)
    assert good["failure_mode"] == "pass" and good["metrics"]["score"] == 1.0
    wrong_mag = dict(gt, posterior_world1=(
        str(Fraction(1, 7) if gt["posterior_world1"] != "1/7" else Fraction(1, 8))
    ))
    bad = inst.grade(wrong_mag, 1.0)
    assert bad["failure_mode"] == "wrong_magnitude" and bad["metrics"]["score"] == 0.0
    malformed = inst.grade({"posterior_world1": "soon", "direction": "increased",
                            "justification": "x"}, 1.0)
    assert malformed["failure_mode"] == "answer_format_invalid"


def test_unknown_axis_values_raise_value_error() -> None:
    with pytest.raises(ValueError):
        CORE.build_instance(observation="quiet", protocol="single",
                            prior="uniform", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(observation="silence", protocol="triple",
                            prior="uniform", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(observation="silence", protocol="single",
                            prior="wide", scenario="office", seed=0)
    with pytest.raises(ValueError):
        CORE.build_instance(observation="silence", protocol="single",
                            prior="uniform", scenario="harbor", seed=0)
