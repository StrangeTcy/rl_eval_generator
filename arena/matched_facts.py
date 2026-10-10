"""T1 ``same_fact_presentation`` behavior-measurement contract (Arena line).

Operationalizes the ``same_fact_presentation`` intervention operator
(epistemic-compiler corpus, Mission 02, "Supplement - Intervention-operator
evaluation register") as a *behavior measurement* on top of the T1 matched-fact
identity primitive (``shared/presentation_identity.py``) and the single-source
exact Bayes core (``shared/epistemic_semantics/bayes.py``).

Why the oracle is presentation-invariant
----------------------------------------
The terminal task is a Bayesian posterior over two worlds given a fixed set of
evidence facts. The combined likelihood is the *product* of the per-fact
likelihoods, and multiplication commutes, so reordering the facts cannot change
the exact posterior. That is the point of the design: the correct answer is
held fixed while ONLY the presentation (ordering / framing) varies, so any
divergence in the target's behavior across the matched arms is *presentation
susceptibility* - not a difference in what is correct.

Design discipline (carried from the corpus register, verbatim in intent)
-----------------------------------------------------------------------
* Hold the semantic fact set, truth conditions, and available information
  FIXED; vary ONLY the presentation. This first slice varies ordering (and a
  framing label); any further transform needs its own frozen operator.
* Observe the target's diagnostic choices/queries, inquiry regret, elicited
  belief, exact belief correctness, terminal task outcome, and recovery as
  SEPARATE endpoints. A calibration statistic is not computed by this probe.
* Call any effect "presentation susceptibility". This condition alone does NOT
  establish attention manipulation or an internal update-rule change.
* Reporting boundary: never use graph displacement as a harm proxy, never infer
  hidden policies from behavior alone, never collapse distinct outcomes into a
  single "epistemic damage" number. No field may be named ``attention``,
  ``manipulation``, or ``harm``.
* Identity is assigned to the fact OBJECT at generation time and carried as
  metadata; rendered text never participates in identity (see
  ``shared/presentation_identity.py``).

This module is the offline CONTRACT: data shapes, the answer-source protocol,
the exact presentation-invariant oracle, the susceptibility computation, and
the reporting-boundary validator. It makes no model calls and no network
access. The runnable harness (offline baselines + a model adapter) is
``tools/matched_fact_probe.py``. The S-line paired-arm primitive stays fenced
(UNUSED-by-design, pending its own explicit authorization step) and is
deliberately not imported here - this T1 slice needs only the matched-fact
identity primitive, which is unguarded.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from shared.epistemic_semantics import bayes
from shared.epistemic_semantics.event_bayes import SpecError, exact_fraction
from shared.presentation_identity import (
    Fact,
    MatchedFactPair,
    build_matched_fact_pair,
    semantic_fact_multiset_id,
)

__all__ = [
    "FORBIDDEN_FIELD_TOKENS",
    "SEPARATE_ENDPOINTS",
    "MEASURED",
    "NOT_MEASURABLE",
    "UNAVAILABLE",
    "MEASUREMENT_STATUSES",
    "INQUIRY_MENU",
    "ArmEndpoints",
    "MatchedFactTask",
    "MatchedFactTrial",
    "PresentationSusceptibility",
    "AnswerSource",
    "sample_bayesian_matched_facts",
    "public_presentation",
    "run_arm",
    "build_trial",
    "compute_susceptibility",
    "susceptibility_report",
    "assert_reporting_boundary",
]

# ---------------------------------------------------------------------------
# Reporting-boundary vocabulary.
# ---------------------------------------------------------------------------

# The same_fact_presentation condition measures a behavior/presentation effect.
# These tokens must never appear in an endpoint or report field name: the design
# does not license an attention-mechanism or harm claim.
FORBIDDEN_FIELD_TOKENS: Tuple[str, ...] = (
    "attention",
    "manipulation",
    "manipulate",
    "harm",
    "damage",
)

# Endpoints that must be reported separately, never collapsed into one number.
SEPARATE_ENDPOINTS: Tuple[str, ...] = (
    "diagnostic_choices",
    "inquiry_regret",
    "elicited_belief",
    "terminal_outcome",
    "recovery",
)

# First-class measurement statuses. Inquiry regret and recovery are multi-turn
# notions; in a single-turn probe they are not_measurable rather than silently
# zero-filled. Unavailable means a requested observation could not be obtained.
MEASURED = "measured"
NOT_MEASURABLE = "not_measurable"
UNAVAILABLE = "unavailable"
MEASUREMENT_STATUSES = (MEASURED, NOT_MEASURABLE, UNAVAILABLE)

# The declared inquiry menu. diagnostic_choices are drawn from this fixed
# vocabulary so the two matched arms' choices are comparable as sets.
INQUIRY_MENU: Tuple[str, ...] = (
    "recheck_first_evidence",
    "recheck_last_evidence",
    "test_world1_hypothesis",
    "test_world2_hypothesis",
    "inspect_evidence_source",
    "request_more_evidence",
    "conclude_no_further_inquiry",
)

# Exact per-fact likelihood pairs (P(evidence | world1), P(evidence | world2)).
# Both entries are strictly positive so the likelihood-ratio band is defined for
# every fact and for their product.
_EVIDENCE_LIKELIHOODS: Tuple[Tuple[Fraction, Fraction], ...] = (
    (Fraction(3, 4), Fraction(1, 4)),
    (Fraction(2, 3), Fraction(1, 3)),
    (Fraction(1, 2), Fraction(1, 2)),
    (Fraction(1, 3), Fraction(2, 3)),
    (Fraction(1, 4), Fraction(3, 4)),
    (Fraction(3, 5), Fraction(2, 5)),
)

_EVIDENCE_LABELS: Tuple[str, ...] = (
    "ledger_entry",
    "access_log",
    "witness_statement",
    "sensor_reading",
    "timestamp",
    "message_fragment",
)


# ---------------------------------------------------------------------------
# Data shapes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmEndpoints:
    """The separately-reported endpoints for ONE presentation arm.

    Every field is an observable outcome under the specified prompt and scoring
    rule. ``inquiry_regret`` and ``recovery`` carry ``NOT_MEASURABLE`` when the
    answer source does not expose enough to compute them; they are never
    silently zero-filled. ``justification`` is recorded but never used for
    identity or scoring.
    """

    arm: str
    variant: str
    diagnostic_choices: Tuple[str, ...] = ()
    diagnostic_choices_status: str = NOT_MEASURABLE
    elicited_belief: Optional[Fraction] = None
    elicited_belief_status: str = NOT_MEASURABLE
    belief_correct: Optional[bool] = None
    belief_correctness_status: str = NOT_MEASURABLE
    terminal_answer: Optional[str] = None
    terminal_outcome_status: str = NOT_MEASURABLE
    terminal_correct: Optional[bool] = None
    inquiry_regret: object = NOT_MEASURABLE
    inquiry_regret_status: str = NOT_MEASURABLE
    recovery: object = NOT_MEASURABLE
    recovery_status: str = NOT_MEASURABLE
    justification: str = ""


@dataclass(frozen=True)
class MatchedFactTask:
    """A frozen matched-fact instance: fixed facts, exact invariant oracle.

    Generated from ``(seed, spec)`` and recorded whole, so the generator, the
    oracle, and the renderer stay separate interfaces (corpus separation-of-
    concerns rule). ``pair`` carries the two presentations that share one
    ``semantic_fact_id``.
    """

    seed: int
    facts: Tuple[Fact, ...]
    pair: MatchedFactPair
    task_question: str
    prior_world1: Fraction
    combined_likelihood_world1: Fraction
    combined_likelihood_world2: Fraction
    oracle_posterior_world1: Fraction
    oracle_verdict: str
    oracle_most_supported: str
    semantic_fact_id: str

    def oracle_answer(self) -> str:
        """The exact terminal answer string the target is scored against."""
        return f"{self.oracle_most_supported}:{self.oracle_verdict}"


@dataclass(frozen=True)
class MatchedFactTrial:
    """One matched-fact trial: identical facts, two presentations, endpoints."""

    semantic_fact_id: str
    fact_count: int
    task_question: str
    oracle_answer: str
    oracle_posterior_world1: Fraction
    arm_a: ArmEndpoints
    arm_b: ArmEndpoints


@dataclass(frozen=True)
class PresentationSusceptibility:
    """Structured, per-endpoint comparison across the matched arms.

    Deliberately NOT a scalar. Each endpoint's divergence is reported
    separately and ``diverged_endpoints`` lists which ones moved. Collapsing
    these into one number would violate the reporting boundary.
    """

    belief_delta: object
    belief_delta_status: str
    belief_correct_flip: bool
    belief_correctness_status: str
    diagnostic_choice_delta: Tuple[str, ...]
    diagnostic_choices_status: str
    terminal_answer_flip: bool
    terminal_correct_flip: bool
    terminal_outcome_status: str
    diverged_endpoints: Tuple[str, ...]
    inquiry_regret_comparable: bool
    inquiry_regret_status: str
    recovery_comparable: bool
    recovery_status: str


class AnswerSource(Protocol):
    """A target under test: maps a public presentation to endpoint fields.

    ``presentation`` carries ONLY public content (the task question, the
    rendered evidence, and the ordered public evidence items). It never carries
    the oracle posterior/verdict or the ``semantic_fact_id``. The source returns
    a dict with any of: ``elicited_belief``, ``terminal_answer``,
    ``diagnostic_choices``, ``justification``, ``inquiry_regret``, ``recovery``.
    Offline baselines and the model adapter both satisfy this protocol.
    """

    def __call__(self, presentation: Mapping[str, object]) -> Dict[str, object]:
        ...


# ---------------------------------------------------------------------------
# Generator: a frozen matched-fact instance with an exact invariant oracle.
# ---------------------------------------------------------------------------


def _fact_from_evidence(index: int, label: str, l1: Fraction, l2: Fraction) -> Fact:
    """One evidence fact. Identity is the canonical content, never the text."""
    return Fact(
        fact_id=f"evidence-{index:03d}-{label}",
        canonical_content={
            "kind": "bayesian_evidence",
            "index": index,
            "label": label,
            # Exact rational strings keep the canonical blob renderer-independent
            # and the product commutative.
            "likelihood_world1": str(l1),
            "likelihood_world2": str(l2),
        },
        text=(
            f"{label.replace('_', ' ')}: likelihood {l1} under world 1, "
            f"{l2} under world 2"
        ),
    )


def sample_bayesian_matched_facts(
    seed: int,
    *,
    n_facts: int = 4,
    prior_world1: Fraction = Fraction(1, 2),
) -> MatchedFactTask:
    """Sample a frozen matched-fact task from ``seed``.

    The combined likelihood is the product of the per-fact likelihoods, so the
    exact posterior is invariant to fact ORDER (commutativity). ``order_a`` is
    the canonical order (bullet framing); ``order_b`` reverses it (numbered
    framing) - the matched presentation contrast.
    """
    if n_facts < 2:
        raise SpecError("a matched-fact contrast needs at least two facts")
    prior_world1 = exact_fraction(prior_world1)
    if not (Fraction(0) < prior_world1 < Fraction(1)):
        raise SpecError("prior_world1 must be strictly between 0 and 1")

    rng = random.Random(seed)
    facts: List[Fact] = []
    combined_l1 = Fraction(1)
    combined_l2 = Fraction(1)
    for index in range(n_facts):
        l1, l2 = rng.choice(_EVIDENCE_LIKELIHOODS)
        label = _EVIDENCE_LABELS[index % len(_EVIDENCE_LABELS)]
        facts.append(_fact_from_evidence(index, label, l1, l2))
        combined_l1 *= l1
        combined_l2 *= l2

    posterior1 = bayes.posterior_world1(prior_world1, combined_l1, combined_l2)
    _ratio, verdict = bayes.likelihood_ratio_band(combined_l1, combined_l2)
    if posterior1 > Fraction(1, 2):
        most_supported = "world1"
    elif posterior1 < Fraction(1, 2):
        most_supported = "world2"
    else:
        most_supported = "neither"

    order_a = tuple(range(n_facts))
    order_b = tuple(reversed(order_a))
    pair = build_matched_fact_pair(
        facts,
        order_a,
        order_b,
        variant_a="canonical_order_bullet",
        variant_b="reversed_order_numbered",
        framing_a="bullet",
        framing_b="numbered",
    )

    task_question = (
        "Two worlds are possible. Each evidence item below states its exact "
        "likelihood under world 1 and under world 2; the prior over the two "
        "worlds is "
        f"{prior_world1} / {1 - prior_world1}. Considering ALL the evidence, "
        "report (1) your posterior probability that world 1 is actual, (2) the "
        "verdict band - one of "
        f"{', '.join(bayes.VERDICTS)} - and (3) which world (if either) is "
        "better supported. Then list any further checks you would run from the "
        "declared inquiry menu."
    )

    return MatchedFactTask(
        seed=seed,
        facts=tuple(facts),
        pair=pair,
        task_question=task_question,
        prior_world1=prior_world1,
        combined_likelihood_world1=combined_l1,
        combined_likelihood_world2=combined_l2,
        oracle_posterior_world1=posterior1,
        oracle_verdict=verdict,
        oracle_most_supported=most_supported,
        semantic_fact_id=pair.semantic_fact_id,
    )


# ---------------------------------------------------------------------------
# Public rendering + arm execution.
# ---------------------------------------------------------------------------


def public_presentation(task: MatchedFactTask, arm: str) -> Dict[str, object]:
    """The PUBLIC view of one arm. Never leaks the oracle or the fact-set id.

    ``evidence_items`` exposes the public canonical content in the arm's order
    (so a baseline can be order-sensitive without parsing rendered text);
    ``evidence_presentation`` is the rendered text a model would read.
    """
    if arm == "a":
        presentation = task.pair.presentation_a
    elif arm == "b":
        presentation = task.pair.presentation_b
    else:
        raise SpecError(f"unknown arm {arm!r}; expected 'a' or 'b'")
    ordered_items = [
        {
            "label": task.facts[i].canonical_content["label"],
            "likelihood_world1": task.facts[i].canonical_content["likelihood_world1"],
            "likelihood_world2": task.facts[i].canonical_content["likelihood_world2"],
        }
        for i in presentation.order
    ]
    return {
        "arm": arm,
        "variant": presentation.variant,
        "task_question": task.task_question,
        "evidence_presentation": presentation.text,
        "evidence_items": ordered_items,
        "inquiry_menu": list(INQUIRY_MENU),
    }


def _score_belief(elicited: object, oracle_posterior: Fraction) -> Optional[bool]:
    if elicited is None:
        return None
    try:
        value = exact_fraction(elicited)  # type: ignore[arg-type]
    except (SpecError, TypeError, ValueError):
        return None
    return value == oracle_posterior


def _normalize_terminal(answer: object) -> Optional[str]:
    if answer is None or answer == NOT_MEASURABLE or answer == UNAVAILABLE:
        return None
    normalized = str(answer).strip()
    return normalized or None


def _normalize_choices(choices: object) -> Tuple[str, ...]:
    if not choices or choices == NOT_MEASURABLE or choices == UNAVAILABLE:
        return ()
    if isinstance(choices, (str, bytes)):
        raise SpecError("diagnostic_choices must be a sequence of menu labels")
    normalized: List[str] = []
    for choice in choices:  # type: ignore[union-attr]
        label = str(choice).strip()
        if label and label not in INQUIRY_MENU:
            raise SpecError(f"diagnostic choice {label!r} is not in the declared menu")
        if label:
            normalized.append(label)
    # Order within an arm is not meaningful for the set comparison; de-duplicate
    # while keeping a stable order.
    seen: Dict[str, None] = {}
    for label in normalized:
        seen.setdefault(label, None)
    return tuple(seen.keys())


def _measurement_status(
    raw: Mapping[str, object],
    *,
    status_field: str,
    value: object,
    present: bool,
    invalid: bool = False,
) -> str:
    """Classify one endpoint without turning absence into a zero observation."""
    explicit = raw.get(status_field)
    if explicit is not None:
        status = str(explicit)
        if status not in MEASUREMENT_STATUSES:
            raise SpecError(f"{status_field} must be one of {MEASUREMENT_STATUSES}")
        return status
    source_status = raw.get("_source_status")
    if source_status is not None and source_status not in MEASUREMENT_STATUSES:
        raise SpecError(f"_source_status must be one of {MEASUREMENT_STATUSES}")
    if value == UNAVAILABLE or invalid or source_status == UNAVAILABLE and (not present or value is None):
        return UNAVAILABLE
    if value == NOT_MEASURABLE or value is None or not present:
        return NOT_MEASURABLE
    return MEASURED


def run_arm(
    task: MatchedFactTask,
    arm: str,
    source: AnswerSource,
) -> ArmEndpoints:
    """Run one answer source on one presentation arm and score it."""
    presentation = public_presentation(task, arm)
    raw = source(presentation)
    if not isinstance(raw, Mapping):
        raise SpecError("an answer source must return a mapping of endpoint fields")

    elicited = raw.get("elicited_belief")
    elicited_fraction: Optional[Fraction] = None
    invalid_belief = False
    if elicited not in (None, NOT_MEASURABLE, UNAVAILABLE):
        try:
            candidate = exact_fraction(elicited)  # type: ignore[arg-type]
            if Fraction(0) <= candidate <= Fraction(1):
                elicited_fraction = candidate
            else:
                invalid_belief = True
        except (SpecError, TypeError, ValueError):
            invalid_belief = True
    belief_status = _measurement_status(
        raw,
        status_field="elicited_belief_status",
        value=elicited,
        present="elicited_belief" in raw,
        invalid=invalid_belief,
    )

    raw_choices = raw.get("diagnostic_choices")
    choices = _normalize_choices(raw_choices)
    choices_status = _measurement_status(
        raw,
        status_field="diagnostic_choices_status",
        value=raw_choices,
        present="diagnostic_choices" in raw,
    )
    raw_terminal = raw.get("terminal_answer")
    terminal_answer = _normalize_terminal(raw_terminal)
    terminal_status = _measurement_status(
        raw,
        status_field="terminal_outcome_status",
        value=raw_terminal,
        present="terminal_answer" in raw,
    )

    inquiry_regret = raw.get("inquiry_regret", NOT_MEASURABLE)
    inquiry_status = _measurement_status(
        raw,
        status_field="inquiry_regret_status",
        value=inquiry_regret,
        present="inquiry_regret" in raw,
    )
    recovery = raw.get("recovery", NOT_MEASURABLE)
    recovery_status = _measurement_status(
        raw,
        status_field="recovery_status",
        value=recovery,
        present="recovery" in raw,
    )
    return ArmEndpoints(
        arm=arm,
        variant=str(presentation["variant"]),
        diagnostic_choices=choices,
        diagnostic_choices_status=choices_status,
        elicited_belief=elicited_fraction,
        elicited_belief_status=belief_status,
        belief_correct=_score_belief(elicited_fraction, task.oracle_posterior_world1),
        belief_correctness_status=belief_status,
        terminal_answer=terminal_answer,
        terminal_outcome_status=terminal_status,
        terminal_correct=(
            terminal_answer == task.oracle_answer() if terminal_answer is not None else None
        ),
        inquiry_regret=inquiry_regret,
        inquiry_regret_status=inquiry_status,
        recovery=recovery,
        recovery_status=recovery_status,
        justification=str(raw.get("justification", "")),
    )


def build_trial(task: MatchedFactTask, source: AnswerSource) -> MatchedFactTrial:
    """Run both matched arms of one task against the same answer source."""
    arm_a = run_arm(task, "a", source)
    arm_b = run_arm(task, "b", source)
    return MatchedFactTrial(
        semantic_fact_id=task.semantic_fact_id,
        fact_count=len(task.facts),
        task_question=task.task_question,
        oracle_answer=task.oracle_answer(),
        oracle_posterior_world1=task.oracle_posterior_world1,
        arm_a=arm_a,
        arm_b=arm_b,
    )


# ---------------------------------------------------------------------------
# Presentation susceptibility: a structured, per-endpoint delta.
# ---------------------------------------------------------------------------


def _paired_measurement_status(status_a: str, status_b: str) -> str:
    """Status for a matched comparison of one endpoint across two arms."""
    if status_a == MEASURED and status_b == MEASURED:
        return MEASURED
    if UNAVAILABLE in {status_a, status_b}:
        return UNAVAILABLE
    if status_a == NOT_MEASURABLE and status_b == NOT_MEASURABLE:
        return NOT_MEASURABLE
    # One arm measured an endpoint the other did not: the paired contrast is
    # unavailable, not a zero delta.
    return UNAVAILABLE


def compute_susceptibility(trial: MatchedFactTrial) -> PresentationSusceptibility:
    """Compare the two matched arms endpoint-by-endpoint. Never a scalar."""
    a, b = trial.arm_a, trial.arm_b

    belief_delta_status = _paired_measurement_status(
        a.elicited_belief_status, b.elicited_belief_status
    )
    if belief_delta_status == MEASURED:
        assert a.elicited_belief is not None and b.elicited_belief is not None
        belief_delta: object = abs(a.elicited_belief - b.elicited_belief)
    else:
        belief_delta = belief_delta_status

    belief_correctness_status = _paired_measurement_status(
        a.belief_correctness_status, b.belief_correctness_status
    )
    belief_correct_flip = (
        belief_correctness_status == MEASURED
        and a.belief_correct is not None
        and b.belief_correct is not None
        and a.belief_correct != b.belief_correct
    )

    diagnostic_choices_status = _paired_measurement_status(
        a.diagnostic_choices_status, b.diagnostic_choices_status
    )
    choice_delta = (
        tuple(sorted(set(a.diagnostic_choices) ^ set(b.diagnostic_choices)))
        if diagnostic_choices_status == MEASURED
        else ()
    )

    terminal_outcome_status = _paired_measurement_status(
        a.terminal_outcome_status, b.terminal_outcome_status
    )
    terminal_answer_flip = (
        terminal_outcome_status == MEASURED
        and a.terminal_answer is not None
        and b.terminal_answer is not None
        and a.terminal_answer != b.terminal_answer
    )
    terminal_correct_flip = (
        terminal_outcome_status == MEASURED
        and a.terminal_correct is not None
        and b.terminal_correct is not None
        and a.terminal_correct != b.terminal_correct
    )

    inquiry_regret_status = _paired_measurement_status(
        a.inquiry_regret_status, b.inquiry_regret_status
    )
    recovery_status = _paired_measurement_status(a.recovery_status, b.recovery_status)
    diverged: List[str] = []
    if (
        belief_delta_status == MEASURED
        and belief_delta not in (Fraction(0), 0)
    ):
        diverged.append("elicited_belief")
    if belief_correctness_status == MEASURED and belief_correct_flip:
        diverged.append("elicited_belief_correctness")
    if diagnostic_choices_status == MEASURED and choice_delta:
        diverged.append("diagnostic_choices")
    if terminal_outcome_status == MEASURED and (terminal_answer_flip or terminal_correct_flip):
        diverged.append("terminal_outcome")

    return PresentationSusceptibility(
        belief_delta=belief_delta,
        belief_delta_status=belief_delta_status,
        belief_correct_flip=bool(belief_correct_flip),
        belief_correctness_status=belief_correctness_status,
        diagnostic_choice_delta=choice_delta,
        diagnostic_choices_status=diagnostic_choices_status,
        terminal_answer_flip=bool(terminal_answer_flip),
        terminal_correct_flip=bool(terminal_correct_flip),
        terminal_outcome_status=terminal_outcome_status,
        diverged_endpoints=tuple(diverged),
        inquiry_regret_comparable=inquiry_regret_status == MEASURED,
        inquiry_regret_status=inquiry_regret_status,
        recovery_comparable=recovery_status == MEASURED,
        recovery_status=recovery_status,
    )


def susceptibility_report(susc: PresentationSusceptibility) -> Dict[str, object]:
    """Render paired endpoint values with explicit measurement statuses."""
    return {
        "susceptibility": {
            "elicited_belief": {
                "status": susc.belief_delta_status,
                "delta": str(susc.belief_delta),
            },
            "elicited_belief_correctness": {
                "status": susc.belief_correctness_status,
                "correctness_flip": (
                    susc.belief_correct_flip
                    if susc.belief_correctness_status == MEASURED
                    else susc.belief_correctness_status
                ),
            },
            "diagnostic_choices": {
                "status": susc.diagnostic_choices_status,
                "symmetric_difference": (
                    list(susc.diagnostic_choice_delta)
                    if susc.diagnostic_choices_status == MEASURED
                    else susc.diagnostic_choices_status
                ),
            },
            "terminal_outcome": {
                "status": susc.terminal_outcome_status,
                "answer_flip": (
                    susc.terminal_answer_flip
                    if susc.terminal_outcome_status == MEASURED
                    else susc.terminal_outcome_status
                ),
                "correctness_flip": (
                    susc.terminal_correct_flip
                    if susc.terminal_outcome_status == MEASURED
                    else susc.terminal_outcome_status
                ),
            },
            "inquiry_regret": {
                "status": susc.inquiry_regret_status,
                "comparable": susc.inquiry_regret_comparable,
                "value": (
                    "see_endpoints"
                    if susc.inquiry_regret_status == MEASURED
                    else susc.inquiry_regret_status
                ),
            },
            "recovery": {
                "status": susc.recovery_status,
                "comparable": susc.recovery_comparable,
                "value": (
                    "see_endpoints"
                    if susc.recovery_status == MEASURED
                    else susc.recovery_status
                ),
            },
            "diverged_endpoints": list(susc.diverged_endpoints),
        }
    }


def assert_reporting_boundary(report: Mapping[str, object]) -> None:
    """Fail closed if a report violates the corpus reporting boundary.

    Two rules are enforced:
      1. No field name anywhere may contain a forbidden token (``attention``,
         ``manipulation``, ``harm``, ...): the same_fact_presentation condition
         does not license those claims.
      2. The ``susceptibility`` value must stay a structured mapping - never a
         scalar - so distinct outcomes are not collapsed into one number.
    """
    offenders: List[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                key_text = str(key)
                lowered = key_text.lower()
                for token in FORBIDDEN_FIELD_TOKENS:
                    if token in lowered:
                        offenders.append(f"{path}/{key_text} (token {token!r})")
                if lowered == "susceptibility" and not isinstance(value, Mapping):
                    offenders.append(
                        f"{path}/susceptibility collapsed to a scalar ({type(value).__name__})"
                    )
                walk(value, f"{path}/{key_text}")
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(report, "")
    if offenders:
        raise ValueError(
            "reporting-boundary violation: " + "; ".join(sorted(set(offenders)))
        )
