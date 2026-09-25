"""Call-plan calculation shared by trajectory execution and the CLI."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class TrajectoryPlan:
    system_seed_count: int
    initial_state_seed_count: int
    representation_count: int
    witness_count: int
    query_counts: dict[str, int]
    horizon_counts: dict[str, list[int]]
    relabeling_count: int
    syntax_noise_count: int
    api_replications: int
    case_count: int
    api_call_count: int
    maximum_output_tokens: int
    maximum_output_token_budget: int

    def as_dict(self) -> dict[str, object]:
        return {
            "system_seed_count": self.system_seed_count,
            "initial_state_seed_count": self.initial_state_seed_count,
            "representation_count": self.representation_count,
            "witness_count": self.witness_count,
            "query_counts": self.query_counts,
            "horizon_counts": self.horizon_counts,
            "relabeling_count": self.relabeling_count,
            "syntax_noise_count": self.syntax_noise_count,
            "api_replications": self.api_replications,
            "case_count": self.case_count,
            "api_call_count": self.api_call_count,
            "maximum_output_tokens": self.maximum_output_tokens,
            "maximum_output_token_budget": self.maximum_output_token_budget,
        }


def query_horizons(query: str, horizons: Iterable[int]) -> list[int]:
    """Return only horizons meaningful for a query control."""

    normalized = {
        "parse": "parse_only",
        "parse_only": "parse_only",
        "one_step": "one_step",
        "state_at_t": "state_at_T",
        "state_at_horizon": "state_at_T",
        "template_return": "template_at_T",
        "template_return_at_horizon": "template_at_T",
        "complete_return_at_T": "complete_return",
        "complete_state_return": "complete_return",
    }.get(query, query)
    if normalized == "parse_only":
        return [0]
    if normalized == "one_step":
        return [1]
    values = list(dict.fromkeys(int(value) for value in horizons))
    if not values:
        raise ValueError(f"no horizons supplied for {query}")
    if any(value < 0 for value in values):
        raise ValueError("horizons must be non-negative")
    return values


def build_plan(
    *,
    system_seeds: list[int],
    initial_state_seeds: list[int],
    representations: list[str],
    witnesses: list[str],
    queries: list[str],
    horizons: list[int],
    relabelings: list[str],
    syntax_noise: list[str],
    api_replications: int,
    max_tokens: int,
) -> TrajectoryPlan:
    if len(system_seeds) != len(initial_state_seeds):
        raise ValueError("system-seeds and initial-state-seeds must have equal lengths")
    if not system_seeds:
        raise ValueError("at least one system seed is required")
    if api_replications < 1:
        raise ValueError("api-replications must be positive")
    if max_tokens < 1:
        raise ValueError("max-tokens must be positive")
    horizon_counts = {query: query_horizons(query, horizons) for query in queries}
    per_seed = (
        len(representations)
        * len(witnesses)
        * len(relabelings)
        * len(syntax_noise)
    )
    cases_per_seed = per_seed * sum(len(values) for values in horizon_counts.values())
    case_count = len(system_seeds) * cases_per_seed
    api_call_count = case_count * api_replications
    return TrajectoryPlan(
        system_seed_count=len(system_seeds),
        initial_state_seed_count=len(initial_state_seeds),
        representation_count=len(representations),
        witness_count=len(witnesses),
        query_counts={query: len(values) for query, values in horizon_counts.items()},
        horizon_counts=horizon_counts,
        relabeling_count=len(relabelings),
        syntax_noise_count=len(syntax_noise),
        api_replications=api_replications,
        case_count=case_count,
        api_call_count=api_call_count,
        maximum_output_tokens=max_tokens,
        maximum_output_token_budget=api_call_count * max_tokens,
    )
