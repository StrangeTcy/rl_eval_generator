"""Strategy IR cards: conformance to the protocol's documented field list.

Upstream (`research_protocol/strategy_ir.md`) says plainly that its YAML "is not currently a
machine-enforced schema" and that `scripts/validate_ir.py` is not implemented, while also
insisting a card must not be promoted because its prose sounds plausible. Those two statements
together are what this file enforces locally: the field list, the enums, and one promotion
rule, so a card in this repository is checked against something other than its own wording.

The family ids below are copied from `research_protocol/strategy_families.yaml` as a *file
contract*, the same way the causal-layer ADR handles an absent upstream: this repository does
not import from that checkout, and a test that imports what may not exist is a test that fails
for the wrong reason.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CARD_DIR = ROOT / "spec" / "strategy-ir"

STRATEGY_FAMILIES = {
    "representation", "invariant", "asymmetry", "decomposition", "elimination", "constraint",
    "counterexample", "meta", "search", "game", "local_to_global", "transformation",
}
STATUSES = {"candidate", "under_test", "supported_in_scope", "disconfirmed_in_scope", "retired"}
ORIGINS = {"source-backed", "episode-derived", "user-proposed", "agent-proposed"}
REVIEW_STATUSES = {"unreviewed", "human_reviewed"}
OUTCOMES = {"solved", "reduced", "no_effect", "invalid_transform", "inconclusive"}

CARD_REQUIRED = (
    "strategy_id", "version", "name", "family", "status", "scope", "trigger", "transformation",
    "expected_effect", "obligations", "failure_modes", "validation", "exemplars",
    "counterexamples", "related_strategy_ids", "provenance",
)
CARD_NESTED = {
    "scope": ("problem_classes", "preconditions"),
    "trigger": ("structural_conditions", "diagnostic_questions", "exclusion_conditions"),
    "transformation": ("input_representation", "operation", "output_representation"),
    "expected_effect": ("measurable_prediction", "outcome_measure"),
    "validation": ("discriminating_tests", "baseline", "falsification_condition"),
    "provenance": ("origin", "source_refs", "episode_refs", "review_status"),
}
APPLICATION_REQUIRED = (
    "application_id", "problem_state_ref", "strategy_ref", "trigger_evidence",
    "selection_rationale", "input_state_ref", "transformation_record", "output_state_ref",
    "obligation_checks", "outcome", "measurement_refs", "review_status",
)


def _cards() -> list[dict]:
    cards: list[dict] = []
    for path in sorted(CARD_DIR.glob("*.yaml")):
        if path.name == "applications.yaml":
            continue
        documents = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
        assert documents, path
        cards.extend(documents)
    return cards


def _applications() -> list[dict]:
    data = yaml.safe_load((CARD_DIR / "applications.yaml").read_text(encoding="utf-8"))
    return list(data["applications"])


@pytest.mark.parametrize("card", _cards(), ids=lambda c: f"{c.get('strategy_id')}-v{c.get('version')}")
def test_a_card_carries_every_field_the_schema_lists(card: dict) -> None:
    for field in CARD_REQUIRED:
        assert field in card, f"missing required field {field!r}"
    for parent, children in CARD_NESTED.items():
        for child in children:
            assert child in (card[parent] or {}), f"{parent}.{child} is required"
    assert re.fullmatch(r"[a-z0-9][a-z0-9_]*", str(card["strategy_id"])), card["strategy_id"]
    assert isinstance(card["version"], int) and card["version"] >= 1
    assert card["family"] in STRATEGY_FAMILIES, card["family"]
    assert card["status"] in STATUSES, card["status"]
    assert card["provenance"]["origin"] in ORIGINS, card["provenance"]["origin"]
    assert card["provenance"]["review_status"] in REVIEW_STATUSES
    # Lists the schema draws as lists must be lists, and the ones that carry the claim
    # must not be empty: an empty obligations list means nothing was required of the move.
    for field in ("obligations", "failure_modes", "exemplars"):
        assert isinstance(card[field], list), field
    for field in ("obligations", "failure_modes"):
        assert card[field], f"{field} must not be empty"
    for field in ("problem_classes", "preconditions"):
        assert card["scope"][field], f"scope.{field} must not be empty"
    assert card["trigger"]["structural_conditions"], "a card with no trigger is not retrievable"


@pytest.mark.parametrize("card", _cards(), ids=lambda c: f"{c.get('strategy_id')}-v{c.get('version')}")
def test_an_unreviewed_card_cannot_be_promoted_and_a_disconfirmation_needs_an_artifact(card: dict) -> None:
    """The protocol's warning, made mechanical in the direction that can hurt.

    Promotion on plausible prose is what the upstream file warns against, so `unreviewed`
    blocks `supported_in_scope`. Demotion is not symmetric: recording a disconfirmation is
    how a false claim gets withdrawn, and it is gated instead on evidence - a card may only
    be disconfirmed_in_scope if it names a concrete counterexample.
    """
    if card["provenance"]["review_status"] == "unreviewed":
        assert card["status"] != "supported_in_scope", (
            f"{card['strategy_id']} claims support without human review"
        )
    if card["status"] == "disconfirmed_in_scope":
        assert card["counterexamples"], "a disconfirmation must point at a failing case"
        assert any(
            ref.startswith(("experiments/", "spec/")) or ref.startswith("https://")
            for ref in card["provenance"]["source_refs"]
        ), "a disconfirmation must cite where the failing case is recorded"


def test_related_ids_and_application_refs_resolve() -> None:
    cards = _cards()
    identities = {(str(c["strategy_id"]), int(c["version"])) for c in cards}
    ids = {strategy_id for strategy_id, _version in identities}
    for card in cards:
        for related in card["related_strategy_ids"]:
            assert related in ids, f"{card['strategy_id']} relates to unknown strategy {related!r}"
    for application in _applications():
        ref = application["strategy_ref"]
        assert (str(ref["strategy_id"]), int(ref["version"])) in identities, application["application_id"]


@pytest.mark.parametrize("application", _applications(), ids=lambda a: a.get("application_id"))
def test_an_application_record_is_a_trace_not_a_label(application: dict) -> None:
    for field in APPLICATION_REQUIRED:
        assert field in application, f"missing {field!r}"
    assert application["outcome"] in OUTCOMES, application["outcome"]
    assert application["review_status"] in REVIEW_STATUSES
    for field in ("trigger_evidence", "obligation_checks", "measurement_refs"):
        assert application[field], f"{field} empty: the trace asserts without recording"
    # input and output must be different references, or nothing was transformed; and a
    # "solved" record has to show the obligations it passed to be allowed to say so.
    assert application["input_state_ref"] != application["output_state_ref"], application["application_id"]
    if application["outcome"] == "solved":
        assert len(application["obligation_checks"]) >= 2, application["application_id"]


def test_the_operator_text_a_card_points_at_exists() -> None:
    """Every transformation_record naming a file must name one that is in the repository:
    a card whose instruction cannot be handed to a model is a description, not a strategy."""
    for application in _applications():
        record = str(application["transformation_record"])
        if record.endswith(".md"):
            assert (ROOT / record).is_file(), record
