"""Falsification tests for the T1 same_fact_presentation behavior probe.

Grounding (epistemic-compiler corpus, Mission 02): the intervention-operator
evaluation register requires that the same_fact_presentation condition hold the
semantic fact set fixed, vary only presentation, and report diagnostic choices,
elicited belief, terminal outcome, inquiry regret and recovery as SEPARATE
endpoints - calling any effect "presentation susceptibility", never attention
manipulation or harm, and never collapsing outcomes into one number.
"""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.matched_facts import (  # noqa: E402
    FORBIDDEN_FIELD_TOKENS,
    INQUIRY_MENU,
    NOT_MEASURABLE,
    assert_reporting_boundary,
    build_trial,
    compute_susceptibility,
    public_presentation,
    run_arm,
    sample_bayesian_matched_facts,
    susceptibility_report,
)
from shared.epistemic_semantics import bayes  # noqa: E402
from shared.epistemic_semantics.event_bayes import SpecError  # noqa: E402
from tools.matched_fact_probe import (  # noqa: E402
    BASELINES,
    load_profile,
    make_model_source,
    plan_from_profile,
    prior_anchored,
    run_probe,
    run_profile,
)


# ---------------------------------------------------------------------------
# Generator + matched design invariants.
# ---------------------------------------------------------------------------


def test_generator_is_deterministic_and_exact() -> None:
    t1 = sample_bayesian_matched_facts(seed=3, n_facts=4)
    t2 = sample_bayesian_matched_facts(seed=3, n_facts=4)
    assert t1.semantic_fact_id == t2.semantic_fact_id
    assert t1.oracle_posterior_world1 == t2.oracle_posterior_world1
    assert isinstance(t1.oracle_posterior_world1, Fraction)
    assert t1.oracle_verdict in bayes.VERDICTS


def test_oracle_is_presentation_invariant_by_commutativity() -> None:
    """Reordering the facts cannot move the exact posterior (product commutes)."""
    task = sample_bayesian_matched_facts(seed=11, n_facts=5)
    # Recompute the posterior from the reversed fact order; it must be identical.
    rev_l1 = Fraction(1)
    rev_l2 = Fraction(1)
    for fact in reversed(task.facts):
        rev_l1 *= Fraction(str(fact.canonical_content["likelihood_world1"]))
        rev_l2 *= Fraction(str(fact.canonical_content["likelihood_world2"]))
    assert rev_l1 == task.combined_likelihood_world1
    assert rev_l2 == task.combined_likelihood_world2
    assert bayes.posterior_world1(task.prior_world1, rev_l1, rev_l2) == task.oracle_posterior_world1


def test_matched_arms_share_one_id_but_differ_in_presentation() -> None:
    task = sample_bayesian_matched_facts(seed=5, n_facts=4)
    a, b = task.pair.presentation_a, task.pair.presentation_b
    assert a.fact_set_id == b.fact_set_id == task.semantic_fact_id
    assert a.order != b.order
    assert a.text != b.text
    assert a.variant != b.variant
    # Framing differs (bullet vs numbered)...
    assert a.text.splitlines()[0].startswith("- ")
    assert b.text.splitlines()[0].startswith("1. ")
    # ...while the underlying fact CONTENT is the same multiset in both arms.
    def _strip(line: str) -> str:
        return line.lstrip("-0123456789. ").strip()
    assert sorted(_strip(x) for x in a.text.splitlines()) == sorted(
        _strip(x) for x in b.text.splitlines()
    )


def test_public_presentation_leaks_no_oracle_or_identity() -> None:
    task = sample_bayesian_matched_facts(seed=9, n_facts=4)
    for arm in ("a", "b"):
        pres = public_presentation(task, arm)
        # No oracle-labeled field, no fact-set identity, and the combined oracle
        # answer string is never handed to the target. (The posterior itself is
        # legitimately derivable from the public likelihoods - that is the task.)
        assert not any("oracle" in key.lower() for key in pres)
        assert task.semantic_fact_id not in repr(pres)
        assert task.oracle_answer() not in repr(pres)
        assert set(pres["inquiry_menu"]) == set(INQUIRY_MENU)
    # The two arms expose the evidence in different orders.
    labels_a = [i["label"] for i in public_presentation(task, "a")["evidence_items"]]
    labels_b = [i["label"] for i in public_presentation(task, "b")["evidence_items"]]
    assert labels_a == list(reversed(labels_b))


def test_generator_rejects_degenerate_specs() -> None:
    with pytest.raises(SpecError):
        sample_bayesian_matched_facts(seed=1, n_facts=1)
    with pytest.raises(SpecError):
        sample_bayesian_matched_facts(seed=1, n_facts=4, prior_world1=Fraction(0))
    with pytest.raises(SpecError):
        sample_bayesian_matched_facts(seed=1, n_facts=4, prior_world1=Fraction(1))


# ---------------------------------------------------------------------------
# Susceptibility metric: silent on order-invariant, fires on order-sensitive.
# ---------------------------------------------------------------------------


def test_calibrated_baseline_shows_zero_susceptibility() -> None:
    """A correct order-invariant target must NOT be flagged (negative control)."""
    for seed in range(10):
        task = sample_bayesian_matched_facts(seed=seed, n_facts=4)
        trial = build_trial(task, BASELINES["calibrated"](task))
        susc = compute_susceptibility(trial)
        assert susc.diverged_endpoints == ()
        assert susc.belief_delta == Fraction(0)
        assert not susc.terminal_answer_flip
        assert trial.arm_a.terminal_correct and trial.arm_b.terminal_correct


def test_prior_anchored_is_order_invariant_but_incorrect() -> None:
    task = sample_bayesian_matched_facts(seed=4, n_facts=4)
    trial = build_trial(task, prior_anchored)
    susc = compute_susceptibility(trial)
    assert susc.diverged_endpoints == ()  # insensitive to order...
    assert trial.arm_a.belief_correct in (False, None)  # ...but not correct


def test_primacy_and_recency_are_flagged_order_sensitive() -> None:
    """Positive controls: order-sensitive sources must be detected on some seed."""
    detected_primacy = 0
    detected_recency = 0
    for seed in range(12):
        task = sample_bayesian_matched_facts(seed=seed, n_facts=4)
        sp = compute_susceptibility(build_trial(task, BASELINES["primacy_biased"](task)))
        sr = compute_susceptibility(build_trial(task, BASELINES["recency_biased"](task)))
        if sp.diverged_endpoints:
            detected_primacy += 1
        if sr.diverged_endpoints:
            detected_recency += 1
    assert detected_primacy > 0
    assert detected_recency > 0


def test_divergence_is_reported_per_endpoint_not_collapsed() -> None:
    task = sample_bayesian_matched_facts(seed=1, n_facts=4)
    susc = compute_susceptibility(build_trial(task, BASELINES["primacy_biased"](task)))
    report = susceptibility_report(susc)
    block = report["susceptibility"]
    # Each endpoint is a separate structured entry.
    for endpoint in ("elicited_belief", "diagnostic_choices", "terminal_outcome",
                     "inquiry_regret", "recovery"):
        assert endpoint in block
    # No single scalar summary of "how much" susceptibility there is.
    assert not any(isinstance(v, (int, float)) for v in block.values())


def test_single_turn_inquiry_regret_and_recovery_are_not_measurable() -> None:
    task = sample_bayesian_matched_facts(seed=2, n_facts=4)
    trial = build_trial(task, BASELINES["calibrated"](task))
    assert trial.arm_a.inquiry_regret == NOT_MEASURABLE
    assert trial.arm_a.recovery == NOT_MEASURABLE
    susc = compute_susceptibility(trial)
    assert not susc.inquiry_regret_comparable
    assert not susc.recovery_comparable


# ---------------------------------------------------------------------------
# Reporting boundary.
# ---------------------------------------------------------------------------


def test_reporting_boundary_rejects_forbidden_field_names() -> None:
    for token in FORBIDDEN_FIELD_TOKENS:
        with pytest.raises(ValueError):
            assert_reporting_boundary({"susceptibility": {f"{token}_score": {"delta": "0"}}})


def test_reporting_boundary_rejects_scalar_collapse() -> None:
    with pytest.raises(ValueError):
        assert_reporting_boundary({"susceptibility": 0.42})
    with pytest.raises(ValueError):
        assert_reporting_boundary({"susceptibility": "high"})


def test_reporting_boundary_accepts_structured_report() -> None:
    task = sample_bayesian_matched_facts(seed=6, n_facts=4)
    susc = compute_susceptibility(build_trial(task, BASELINES["primacy_biased"](task)))
    assert_reporting_boundary(susceptibility_report(susc))  # must not raise


# ---------------------------------------------------------------------------
# Scoring + answer-source contract.
# ---------------------------------------------------------------------------


def test_terminal_and_belief_scoring_against_exact_oracle() -> None:
    task = sample_bayesian_matched_facts(seed=8, n_facts=4)

    def correct(pres):
        return {
            "elicited_belief": task.oracle_posterior_world1,
            "terminal_answer": task.oracle_answer(),
            "diagnostic_choices": ["conclude_no_further_inquiry"],
        }

    arm = run_arm(task, "a", correct)
    assert arm.terminal_correct is True
    assert arm.belief_correct is True

    def wrong(pres):
        return {"elicited_belief": Fraction(1, 2), "terminal_answer": "world2:distinguishable",
                "diagnostic_choices": []}

    arm_w = run_arm(task, "a", wrong)
    assert arm_w.terminal_correct is False


def test_diagnostic_choices_must_come_from_the_declared_menu() -> None:
    task = sample_bayesian_matched_facts(seed=8, n_facts=4)

    def bad_choice(pres):
        return {"diagnostic_choices": ["not_in_the_menu"]}

    with pytest.raises(SpecError):
        run_arm(task, "a", bad_choice)


# ---------------------------------------------------------------------------
# Model adapter (offline: a fake client, no network).
# ---------------------------------------------------------------------------


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeCompletion(self._content)


def test_model_adapter_parses_structured_response_and_hides_oracle() -> None:
    task = sample_bayesian_matched_facts(seed=13, n_facts=4)
    content = (
        'Here you go:\n{"posterior_world1": "0.6", "verdict": "weakly_distinguishable",'
        ' "most_supported": "world1", "diagnostic_choices": ["test_world1_hypothesis"],'
        ' "justification": "evidence favors world 1"}'
    )
    client = _FakeClient(content)
    source = make_model_source(client, "mercury-2.5", reasoning_effort="high")
    arm = run_arm(task, "a", source)
    assert arm.elicited_belief == Fraction(3, 5)  # exact from the decimal literal
    assert arm.terminal_answer == "world1:weakly_distinguishable"
    assert arm.diagnostic_choices == ("test_world1_hypothesis",)
    # The prompt carried the reasoning knob and never the oracle answer.
    call = client.calls[0]
    assert call["request_extra"] == {"reasoning_effort": "high"}
    prompt = call["messages"][0]["content"]
    assert task.oracle_answer() not in prompt
    assert task.semantic_fact_id not in prompt


def test_model_adapter_survives_unparseable_response() -> None:
    task = sample_bayesian_matched_facts(seed=14, n_facts=4)
    client = _FakeClient("I cannot answer that.")
    source = make_model_source(client, "mercury-2.5")
    arm = run_arm(task, "a", source)  # must not raise
    assert arm.elicited_belief is None
    assert arm.terminal_answer is None
    assert arm.terminal_correct is None
    assert arm.justification == "unparseable_response"


# ---------------------------------------------------------------------------
# Harness end-to-end.
# ---------------------------------------------------------------------------


def test_run_probe_emits_boundary_safe_report_with_separate_endpoints() -> None:
    report = run_probe(BASELINES["primacy_biased"], seeds=list(range(6)), n_facts=4)
    assert report["operator"] == "same_fact_presentation"
    agg = report["aggregate"]
    assert agg["trial_count"] == 6
    assert agg["order_sensitive_trials"] > 0
    # The aggregate reports endpoints separately; there is no single score key.
    assert "diverged_endpoint_histogram" in agg
    assert not any("score" in k for k in agg)
    assert_reporting_boundary(report)  # must not raise


# ---------------------------------------------------------------------------
# Campaign profile + offline preflight (the "matrix" for a target).
# ---------------------------------------------------------------------------


def test_mercury_profile_plans_a_covering_matrix_within_budget() -> None:
    profile = load_profile("experiments/t1_mercury.yaml")
    plan = plan_from_profile(profile)
    assert plan["provider"] == "mercury"
    assert plan["model"] == "mercury-2.5"
    assert plan["reasoning_effort"] == "high"
    # 3 n_facts x 2 priors = 6 cells; 6 x 24 seeds x 2 arms = 288 calls.
    assert plan["cell_count"] == 6
    assert plan["seed_count"] == 24
    assert plan["planned_api_calls"] == 288
    assert plan["within_budget"] is True


def test_budget_gate_fires_before_any_provider_access() -> None:
    """The call ceiling is checked before a key is resolved (offline-safe gate)."""
    profile = {
        "target": {"provider": "mercury", "model": "mercury-2.5"},
        "matrix": {"seeds": 10, "n_facts": [3, 4, 5], "prior_world1": ["1/2", "1/3"]},
        "budget": {"max_api_calls": 5},  # 6 x 10 x 2 = 120 planned >> 5
    }
    assert plan_from_profile(profile)["within_budget"] is False
    with pytest.raises(SystemExit):
        run_profile(profile, out=None)  # must raise on budget, never reaching the network


def test_profile_requires_a_target_mapping() -> None:
    with pytest.raises(SystemExit):
        plan_from_profile({"matrix": {"seeds": 2}})



class _FakeResponsesCompletion:
    def __init__(self, content: str, usage=None) -> None:
        self.content = content
        self.usage = usage or {"prompt_tokens": 0, "completion_tokens": 0}


class _FakeResponsesClient:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list = []

    def complete_responses(self, input_text, **kwargs):
        self.calls.append({"input_text": input_text, **kwargs})
        return _FakeResponsesCompletion(
            self._content, {"prompt_tokens": 12, "completion_tokens": 5}
        )


def test_model_adapter_uses_responses_wire_api_with_nested_reasoning_effort() -> None:
    task = sample_bayesian_matched_facts(seed=15, n_facts=4)
    content = (
        '{"posterior_world1": "0.6", "verdict": "weakly_distinguishable",'
        ' "most_supported": "world1", "diagnostic_choices": [],'
        ' "justification": "ok"}'
    )
    client = _FakeResponsesClient(content)
    sink: dict = {}
    source = make_model_source(
        client,
        "Atria-Dawn-Preview",
        reasoning_effort="high",
        max_tokens=1024,
        wire_api="responses",
        usage_sink=sink,
    )
    arm = run_arm(task, "a", source)
    assert arm.terminal_answer == "world1:weakly_distinguishable"
    call = client.calls[0]
    # Nested reasoning + Responses input shape; no Chat-Completions-only fields.
    assert call["reasoning_effort"] == "high"
    assert call["max_output_tokens"] == 1024
    assert call["model"] == "Atria-Dawn-Preview"
    assert "messages" not in call and "request_extra" not in call
    # The public prompt still hides the oracle answer and the fact-set identity.
    assert task.oracle_answer() not in call["input_text"]
    assert task.semantic_fact_id not in call["input_text"]
    # Provenance sink accumulated the reported usage.
    assert sink == {"calls": 1, "prompt_tokens": 12, "completion_tokens": 5}


def test_model_adapter_rejects_unknown_wire_api() -> None:
    client = _FakeResponsesClient("{}")
    with pytest.raises(ValueError):
        make_model_source(client, "m", wire_api="carrier_pigeon")
