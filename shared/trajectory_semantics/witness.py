"""Query-scoped shortcut witness metadata."""
from __future__ import annotations

from dataclasses import dataclass

from .abstract_semantics import query_answer
from .schema import RelaySystem, State


@dataclass(frozen=True)
class WitnessCertificate:
    witness_id: str
    applicable: bool
    status_for_query: str
    verified_valid_on_canonical: bool
    verified_broken_on_sibling: bool
    stale_prediction: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "witness_id": self.witness_id,
            "witness_applicable": self.applicable,
            "witness_status_for_query": self.status_for_query,
            "verified_valid_on_canonical": self.verified_valid_on_canonical,
            "verified_broken_on_witness_broken": self.verified_broken_on_sibling,
            "stale_prediction": self.stale_prediction,
        }


def complete_period_witness(
    system: RelaySystem,
    *,
    initial: State = ("A", 0),
    horizon: int,
    witness_state: str,
    query_type: str,
) -> WitnessCertificate:
    witness_id = "complete_state_period_6_from_A0"
    applicable = query_type in {"complete_return", "complete_return_at_T"} and initial == ("A", 0) and horizon == 6
    if not applicable:
        return WitnessCertificate(witness_id, False, "not_applicable", False, False, None)
    prediction = bool(query_answer(system, initial=initial, query_type=query_type, horizon=horizon))
    if witness_state == "valid":
        return WitnessCertificate(witness_id, True, "valid", prediction is True, False, "yes")
    if witness_state == "broken":
        return WitnessCertificate(witness_id, True, "broken", False, prediction is False, "yes")
    raise ValueError(witness_state)
