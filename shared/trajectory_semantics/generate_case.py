"""Certified case construction for the relay V1 benchmark."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from .abstract_semantics import orbit_metadata, query_answer, valid_relay
from .certify import certify_system_pair
from .relabel import make_mapping
from .render_flat import render_flat
from .render_flat import render_state as render_flat_state
from .render_reflective import render_reflective
from .render_reflective import render_state as render_reflective_state
from .witness import complete_period_witness

QUERY_ALIASES = {
    "parse": "parse_only",
    "parse_only": "parse_only",
    "one_step": "one_step",
    "state_at_t": "state_at_T",
    "state_at_T": "state_at_T",
    "state_at_horizon": "state_at_T",
    "template_return": "template_at_T",
    "template_at_T": "template_at_T",
    "template_return_at_horizon": "template_at_T",
    "complete_return": "complete_return",
    "complete_return_at_T": "complete_return",
    "complete_state_return": "complete_return",
}


@dataclass(frozen=True)
class TrajectoryCase:
    case_id: str
    control_bundle_id: str
    semantic_seed: int
    presentation_seed: int
    semantic_system_id: str
    presentation_pair_id: str
    witness_pair_id: str
    system_family: str
    representation: str
    query_stage: str
    query_type: str
    horizon: int
    initial_state: dict[str, object]
    relabeling: str
    syntax_noise: str
    resource_protocol: str
    spec_text: str
    question: str
    answer_format: str
    expected_answer: str
    stale_witness_prediction: str | None
    benchmark_status: str
    witness_id: str
    witness_status_for_query: str
    witness_applicable: bool
    query_specific_computation: str
    surface_features: dict[str, object]
    orbit_features: dict[str, object]
    certification: dict[str, object]
    epistemic: dict[str, object]

    def as_dict(self, *, include_answer: bool = True) -> dict[str, object]:
        result = asdict(self)
        if not include_answer:
            result.pop("expected_answer", None)
        return result


def _stable_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _answer_format(query_type: str) -> str:
    if query_type == "parse_only":
        return "one token: same, flip, 0, or 1"
    if query_type == "one_step" or query_type == "state_at_T":
        return "state in the form Template(payload)"
    if query_type in {"template_at_T", "complete_return"}:
        return "yes or no"
    raise ValueError(query_type)


def _question(query_type: str, initial: str, horizon: int, payload_labels: dict[int, str]) -> str:
    if query_type == "parse_only":
        return (
            "Parsing control: what payload operation does the third declared template emit? "
            f"Answer exactly one of: same, flip, {payload_labels[0]}, {payload_labels[1]}."
        )
    if query_type == "one_step":
        return f"Starting from {initial}, what is the state after exactly 1 transition?"
    if query_type == "state_at_T":
        return f"Starting from {initial}, what is the state after exactly {horizon} transitions?"
    if query_type == "template_at_T":
        return f"Starting from {initial}, has the template returned after exactly {horizon} transitions?"
    if query_type == "complete_return":
        return f"Starting from {initial}, has the complete state returned after exactly {horizon} transitions?"
    raise ValueError(query_type)


def _initial_state_for_semantic_seed(semantic_seed: int) -> tuple[str, int]:
    states = (("A", 0), ("A", 1), ("B", 0), ("B", 1), ("C", 0), ("C", 1))
    return states[semantic_seed % len(states)]


def _necessary_computation(query_type: str, horizon: int, witness_applicable: bool) -> str:
    if query_type == "parse_only":
        return "inspect the C-rule payload operation"
    if query_type == "one_step":
        return "apply exactly one named transition"
    if query_type == "state_at_T":
        return f"determine the state at the requested horizon T={horizon}"
    if query_type == "template_at_T":
        return f"determine only the template component at T={horizon}"
    if query_type == "complete_return":
        if witness_applicable:
            return "compare the complete state at T=6 with the initial state; the period witness is query-applicable"
        return f"compare the complete state at T={horizon} with the initial state"
    raise ValueError(query_type)


def _format_expected(answer: object, mapping, initial: tuple[str, int], query_type: str) -> str:
    if query_type == "parse_only":
        # The C rule is the only parse fact asked in V1.
        if answer in {"same", "flip"}:
            return str(answer)
        return str(mapping.payloads[int(answer)])
    if query_type in {"template_at_T", "complete_return"}:
        return "yes" if answer else "no"
    template, payload = answer
    return f"{mapping.templates[template]}({mapping.payloads[payload]})"


def make_case(
    *,
    semantic_seed: int,
    presentation_seed: int | None = None,
    representation: str,
    witness_state: str,
    query_type: str,
    horizon: int,
    relabeling: str,
    syntax_noise: str = "clean",
    resource_protocol: str = "answer_only",
    certification: dict[str, object] | None = None,
) -> TrajectoryCase:
    query_type = QUERY_ALIASES.get(query_type, query_type)
    if representation not in {"flat", "reflective"}:
        raise ValueError(representation)
    if presentation_seed is None:
        presentation_seed = semantic_seed
    if witness_state not in {"valid", "broken"}:
        raise ValueError(witness_state)
    if query_type not in {"parse_only", "one_step", "state_at_T", "template_at_T", "complete_return"}:
        raise ValueError(query_type)
    system = valid_relay(
        witness=witness_state,
        system_id=f"relay-{witness_state}-s{semantic_seed}",
        semantic_seed=semantic_seed,
    )
    mapping = make_mapping(relabeling, presentation_seed)
    rendered = (
        render_flat(system, mapping, syntax_noise=syntax_noise)
        if representation == "flat"
        else render_reflective(system, mapping, syntax_noise=syntax_noise)
    )
    initial = _initial_state_for_semantic_seed(semantic_seed)
    rendered_initial = (
        render_flat_state(initial, mapping)
        if representation == "flat"
        else render_reflective_state(initial, mapping)
    )
    raw_answer: object = query_answer(
        system, initial=initial, query_type=query_type, horizon=horizon
    )
    expected = _format_expected(raw_answer, mapping, initial, query_type)
    witness = complete_period_witness(
        system,
        initial=initial,
        horizon=horizon,
        witness_state=witness_state,
        query_type=query_type,
    )
    control_bundle_id = f"relay-s{semantic_seed}-{witness_state}-T{horizon}-{query_type}"
    case_id = _stable_id(
        control_bundle_id,
        presentation_seed,
        representation,
        relabeling,
        syntax_noise,
        resource_protocol,
    )
    orbit = orbit_metadata(system, initial=initial).as_dict()
    if certification is None:
        certification = certify_system_pair(semantic_seed).as_dict()
    surface = {
        "system_description_bytes": len(rendered.encode("utf-8")),
        "quoted_source_fraction": (
            rendered.count('emit_source') / max(1, len(rendered.splitlines()))
            if representation == "reflective"
            else 0.0
        ),
        "relabeling": relabeling,
        "syntax_noise": syntax_noise,
    }
    epistemic = {
        "supported": ["behavioral_sensitivity_to_named_interventions"],
        "not_supported": [
            "serial_depth_measurement",
            "internal_algorithm_identification",
            "instance_complexity_lower_bound",
        ],
    }
    return TrajectoryCase(
        case_id=case_id,
        control_bundle_id=control_bundle_id,
        semantic_seed=semantic_seed,
        presentation_seed=presentation_seed,
        semantic_system_id=system.system_id,
        presentation_pair_id=(
            f"relay-{witness_state}-s{semantic_seed}-p{presentation_seed}-{relabeling}"
        ),
        witness_pair_id=f"relay-s{semantic_seed}-complete-period-6",
        system_family="relay",
        representation=representation,
        query_stage="parse_only" if query_type == "parse_only" else "one_step" if query_type == "one_step" else "trajectory",
        query_type=query_type,
        horizon=horizon,
        initial_state={"template": mapping.templates[initial[0]], "payload": mapping.payloads[initial[1]]},
        relabeling=relabeling,
        syntax_noise=syntax_noise,
        resource_protocol=resource_protocol,
        spec_text=rendered,
        question=_question(query_type, rendered_initial, horizon, mapping.payloads),
        answer_format=_answer_format(query_type),
        expected_answer=expected,
        stale_witness_prediction="yes" if witness.applicable else None,
        benchmark_status="witness_valid" if witness_state == "valid" else "witness_broken",
        witness_id=witness.witness_id,
        witness_status_for_query=witness.status_for_query,
        witness_applicable=witness.applicable,
        query_specific_computation=_necessary_computation(
            query_type, horizon, witness.applicable
        ),
        surface_features=surface,
        orbit_features={"rollout_horizon": horizon, **orbit, "horizon_mod_cycle": horizon % int(orbit["cycle_length"])},
        certification=certification,
        epistemic=epistemic,
    )
