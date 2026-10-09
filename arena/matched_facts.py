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
  belief/calibration, and terminal task outcome as SEPARATE endpoints.
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
    "NOT_MEASURABLE",
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

# First-class "we did not measure this" marker. Inquiry regret and recovery are
# multi-turn notions; in a single-turn probe they are not_measurable rather than
# silently zero-filled (mirrors the repo's not_measurable/unavailable discipline).
NOT_MEASURABLE = "not_measurable"

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
    elicited_belief: Optional[Fraction] = None
    belief_correct: Optional[bool] = None
    terminal_answer: Optional[str] = None
    terminal_correct: Optional[bool] = None
    inquiry_regret: object = NOT_MEASURABLE
    recovery: object = NOT_MEASURABLE
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
    belief_correct_flip: bool
    diagnostic_choice_delta: Tuple[str, ...]
    terminal_answer_flip: bool
    terminal_correct_flip: bool
    diverged_endpoints: Tuple[str, ...]
    inquiry_regret_comparable: bool
    recovery_comparable: bool


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
    if answer is None:
        return None
    return str(answer).strip()


def _normalize_choices(choices: object) -> Tuple[str, ...]:
    if not choices:
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
    elicited_fraction: Optional[Fraction]
    try:
        elicited_fraction = exact_fraction(elicited) if elicited is not None else None  # type: ignore[arg-type]
    except (SpecError, TypeError, ValueError):
        elicited_fraction = None
    terminal_answer = _normalize_terminal(raw.get("terminal_answer"))
    return ArmEndpoints(
        arm=arm,
        variant=str(presentation["variant"]),
        diagnostic_choices=_normalize_choices(raw.get("diagnostic_choices")),
        elicited_belief=elicited_fraction,
        belief_correct=_score_belief(elicited_fraction, task.oracle_posterior_world1),
        terminal_answer=terminal_answer,
        terminal_correct=(
            terminal_answer == task.oracle_answer() if terminal_answer is not None else None
        ),
        inquiry_regret=raw.get("inquiry_regret", NOT_MEASURABLE),
        recovery=raw.get("recovery", NOT_MEASURABLE),
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


def compute_susceptibility(trial: MatchedFactTrial) -> PresentationSusceptibility:
    """Compare the two matched arms endpoint-by-endpoint. Never a scalar."""
    a, b = trial.arm_a, trial.arm_b

    if a.elicited_belief is not None and b.elicited_belief is not None:
        belief_delta: object = abs(a.elicited_belief - b.elicited_belief)
    elif a.elicited_belief is None and b.elicited_belief is None:
        belief_delta = Fraction(0)
    else:
        belief_delta = NOT_MEASURABLE

    belief_correct_flip = (
        a.belief_correct is not None
        and b.belief_correct is not None
        and a.belief_correct != b.belief_correct
    )

    choice_delta = tuple(
        sorted(set(a.diagnostic_choices) ^ set(b.diagnostic_choices))
    )

    terminal_answer_flip = (
        a.terminal_answer is not None
        and b.terminal_answer is not None
        and a.terminal_answer != b.terminal_answer
    )
    terminal_correct_flip = (
        a.terminal_correct is not None
        and b.terminal_correct is not None
        and a.terminal_correct != b.terminal_correct
    )

    diverged: List[str] = []
    if belief_delta not in (Fraction(0), 0) and belief_delta != NOT_MEASURABLE:
        diverged.append("elicited_belief")
    if belief_correct_flip:
        diverged.append("elicited_belief_correctness")
    if choice_delta:
        diverged.append("diagnostic_choices")
    if terminal_answer_flip or terminal_correct_flip:
        diverged.append("terminal_outcome")

    inquiry_regret_comparable = (
        a.inquiry_regret != NOT_MEASURABLE and b.inquiry_regret != NOT_MEASURABLE
    )
    recovery_comparable = a.recovery != NOT_MEASURABLE and b.recovery != NOT_MEASURABLE

    return PresentationSusceptibility(
        belief_delta=belief_delta,
        belief_correct_flip=bool(belief_correct_flip),
        diagnostic_choice_delta=choice_delta,
        terminal_answer_flip=bool(terminal_answer_flip),
        terminal_correct_flip=bool(terminal_correct_flip),
        diverged_endpoints=tuple(diverged),
        inquiry_regret_comparable=bool(inquiry_regret_comparable),
        recovery_comparable=bool(recovery_comparable),
    )


def susceptibility_report(susc: PresentationSusceptibility) -> Dict[str, object]:
    """Render susceptibility as a STRUCTURED mapping with separate endpoints.

    The top-level ``susceptibility`` value is a mapping, never a scalar: the
    reporting boundary forbids collapsing distinct outcomes into one number.
    """
    return {
        "susceptibility": {
            "elicited_belief": {
                "delta": str(susc.belief_delta),
                "correctness_flip": susc.belief_correct_flip,
            },
            "diagnostic_choices": {"symmetric_difference": list(susc.diagnostic_choice_delta)},
            "terminal_outcome": {
                "answer_flip": susc.terminal_answer_flip,
                "correctness_flip": susc.terminal_correct_flip,
            },
            "inquiry_regret": {
                "comparable": susc.inquiry_regret_comparable,
                "value": NOT_MEASURABLE if not susc.inquiry_regret_comparable else "see_endpoints",
            },
            "recovery": {
                "comparable": susc.recovery_comparable,
                "value": NOT_MEASURABLE if not susc.recovery_comparable else "see_endpoints",
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
