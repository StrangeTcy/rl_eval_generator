"""Reference operations over the canonical relay AST."""
from __future__ import annotations

from .schema import OrbitMetadata, RelayRule, RelaySystem, State


def _flip_mask(system_seed: int) -> tuple[bool, bool, bool]:
    """Choose one of four odd-parity Boolean relay maps.

    Every valid sibling has a six-state orbit, while the seed changes the
    abstract transition semantics rather than merely changing presentation
    names. The C edge remains the witness-edit edge in every sibling; the
    broken sibling replaces it with the specified constant ``A(1)`` edge.
    """

    variants = (
        (False, True, False),
        (True, False, False),
        (False, False, True),
        (True, True, True),
    )
    return variants[system_seed % len(variants)]


def valid_relay(
    *,
    witness: str = "valid",
    system_id: str | None = None,
    semantic_seed: int = 0,
    system_seed: int | None = None,
) -> RelaySystem:
    if witness not in {"valid", "broken"}:
        raise ValueError("witness must be valid or broken")
    selected_seed = semantic_seed if system_seed is None else system_seed
    flip_a, flip_b, flip_c = _flip_mask(selected_seed)
    final_rule = (
        RelayRule("C", "A", "flip" if flip_c else "identity")
        if witness == "valid"
        else RelayRule("C", "A", "constant", 1)
    )
    return RelaySystem(
        templates=("A", "B", "C"),
        payload_domain=(0, 1),
        rules=(
            RelayRule("A", "B", "flip" if flip_a else "identity"),
            RelayRule("B", "C", "flip" if flip_b else "identity"),
            final_rule,
        ),
        system_id=system_id or f"relay-{witness}-s{selected_seed}",
    )


def transition(system: RelaySystem, state: State) -> State:
    return system.transition(state)


def rollout(system: RelaySystem, state: State, horizon: int) -> State:
    if horizon < 0:
        raise ValueError("horizon must be non-negative")
    for _ in range(horizon):
        state = transition(system, state)
    return state


def orbit_metadata(system: RelaySystem, initial: State = ("A", 0)) -> OrbitMetadata:
    """Exhaustively find the orbit of a tiny finite system."""

    seen: dict[State, int] = {}
    state = initial
    step = 0
    while state not in seen:
        seen[state] = step
        state = transition(system, state)
        step += 1
        if step > len(system.templates) * len(system.payload_domain) + 1:
            raise RuntimeError("orbit search exceeded finite-state bound")
    return OrbitMetadata(
        transient_length=seen[state],
        cycle_length=step - seen[state],
        cycle_start=state,
    )


def query_answer(
    system: RelaySystem,
    *,
    initial: State,
    query_type: str,
    horizon: int,
) -> object:
    """Compute the abstract answer; rendered labels are applied by the caller."""

    if query_type in {"parse_only", "parse"}:
        rule = system.rule_for("C")
        if rule.payload_op == "identity":
            return "same"
        if rule.payload_op == "flip":
            return "flip"
        return rule.constant
    if query_type == "one_step":
        return transition(system, initial)
    final = rollout(system, initial, horizon)
    if query_type in {"state_at_T", "state_at_t", "state_at_horizon"}:
        return final
    if query_type in {
        "template_at_T",
        "template_return",
        "template_return_at_T",
        "template_return_at_horizon",
    }:
        return final[0] == initial[0]
    if query_type in {"complete_return", "complete_return_at_T", "complete_state_return"}:
        return final == initial
    if query_type == "first_complete_return_time":
        state = initial
        for step in range(1, max(horizon, 1) + 1):
            state = transition(system, state)
            if state == initial:
                return step
        return None
    raise ValueError(f"unknown query type: {query_type}")


def apply_mapping(system: RelaySystem, mapping: dict[str, str], *, system_id: str | None = None) -> RelaySystem:
    """Rename templates while preserving the transition graph."""

    return RelaySystem(
        templates=tuple(mapping[name] for name in system.templates),
        payload_domain=system.payload_domain,
        rules=tuple(
            RelayRule(
                mapping[rule.source],
                mapping[rule.target],
                rule.payload_op,
                rule.constant,
            )
            for rule in system.rules
        ),
        system_id=system_id or system.system_id,
    )
