"""Hard gates for generated trajectory cases."""
from __future__ import annotations

from dataclasses import dataclass

from .abstract_semantics import query_answer, rollout
from .relabel import make_mapping
from .render_flat import render_flat
from .render_flat import render_state as render_flat_state
from .render_reflective import render_reflective
from .render_reflective import render_state as render_reflective_state
from .rendered_parser import concrete_rollout, parse_rendered
from .schema import RelayRule, RelaySystem, State, SurfaceMapping


@dataclass(frozen=True)
class Certification:
    abstract_concrete_agree: bool
    round_trip_ok: bool
    relabeling_equivariant: bool
    witness_validity: bool
    witness_broken: bool
    details: dict[str, object]

    @property
    def certified(self) -> bool:
        return all(
            (
                self.abstract_concrete_agree,
                self.round_trip_ok,
                self.relabeling_equivariant,
                self.witness_validity,
                self.witness_broken,
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "abstract_vs_concrete": self.abstract_concrete_agree,
            "round_trip": self.round_trip_ok,
            "relabeling_equivariant": self.relabeling_equivariant,
            "witness_validity": self.witness_validity,
            "witness_broken": self.witness_broken,
            "certified": self.certified,
            "details": self.details,
        }


def _render(system: RelaySystem, mapping: SurfaceMapping, presentation: str) -> str:
    if presentation == "flat":
        return render_flat(system, mapping)
    if presentation == "reflective":
        return render_reflective(system, mapping)
    raise ValueError(presentation)


def certify_system_pair(seed: int = 0) -> Certification:
    """Certify both witness siblings and both representations exhaustively."""

    # Constructed independently rather than calling valid_relay so this gate
    # catches accidental shared-generator edits.
    masks = (
        (False, True, False),
        (True, False, False),
        (False, False, True),
        (True, True, True),
    )
    flip_a, flip_b, flip_c = masks[(seed // 6) % len(masks)]
    valid = RelaySystem(
        templates=("A", "B", "C"),
        payload_domain=(0, 1),
        rules=(
            RelayRule("A", "B", "flip" if flip_a else "identity"),
            RelayRule("B", "C", "flip" if flip_b else "identity"),
            RelayRule("C", "A", "flip" if flip_c else "identity"),
        ),
        system_id="relay-valid",
    )
    broken = RelaySystem(
        templates=("A", "B", "C"),
        payload_domain=(0, 1),
        rules=(
            RelayRule("A", "B", "flip" if flip_a else "identity"),
            RelayRule("B", "C", "flip" if flip_b else "identity"),
            RelayRule("C", "A", "constant", 1),
        ),
        system_id="relay-broken",
    )
    details: dict[str, object] = {}
    abstract_concrete = True
    round_trip = True
    for system, label in ((valid, "valid"), (broken, "broken")):
        mapping = make_mapping("canonical", seed)
        for presentation in ("flat", "reflective"):
            rendered = _render(system, mapping, presentation)
            parsed = parse_rendered(rendered)
            for template in system.templates:
                for payload in system.payload_domain:
                    initial: State = (template, payload)
                    rendered_initial = (
                        render_flat_state(initial, mapping)
                        if presentation == "flat"
                        else render_reflective_state(initial, mapping)
                    )
                    parsed_state = parsed.state_from_rendered(rendered_initial)
                    if parsed_state != (mapping.templates[template], payload):
                        round_trip = False
                    for horizon in range(0, 13):
                        abstract = rollout(system, initial, horizon)
                        concrete = concrete_rollout(parsed, rendered_initial, horizon)
                        expected_concrete = (mapping.templates[abstract[0]], abstract[1])
                        if concrete != expected_concrete:
                            abstract_concrete = False
            details[f"{label}_{presentation}"] = parsed.presentation

    # The relabeling transformation must commute with every transition on every
    # tiny state, not merely on a random sample.
    relabeling_equivariant = True
    for relabeling in ("permuted_templates", "recoded_payloads", "alpha_renamed"):
        mapping = make_mapping(relabeling, seed)
        for system in (valid, broken):
            for template in system.templates:
                for payload in system.payload_domain:
                    canonical = (template, payload)
                    # Render/parse is the concrete isomorphism check. The
                    # parsed payload labels are strings, so use the renderer
                    # rather than assembling a state string by hand.
                    parsed = parse_rendered(_render(system, mapping, "flat"))
                    rendered_state = render_flat_state(canonical, mapping)
                    parsed_state = parsed.state_from_rendered(rendered_state)
                    actual = parsed.system.transition(parsed_state)
                    abstract_next = system.transition(canonical)
                    expected = (
                        mapping.templates[abstract_next[0]],
                        abstract_next[1],
                    )
                    if actual != expected:
                        relabeling_equivariant = False

    valid_return = query_answer(valid, initial=("A", 0), query_type="complete_return", horizon=6)
    broken_return = query_answer(broken, initial=("A", 0), query_type="complete_return", horizon=6)
    witness_validity = valid_return is True
    witness_broken = broken_return is False
    details["valid_complete_return_T6"] = valid_return
    details["broken_complete_return_T6"] = broken_return
    return Certification(
        abstract_concrete,
        round_trip,
        relabeling_equivariant,
        witness_validity,
        witness_broken,
        details,
    )
