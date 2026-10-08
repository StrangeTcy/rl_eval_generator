"""Typed, provider-free schema for causal experiment families.

The ordinary suite manifest describes *which task* to run.  This module adds a
separate design layer describing what is being intervened on, which variants are
counterfactual twins, and which behavioral relations are expected.  It does not
pretend that metadata alone materializes an intervention: a family remains
``design_only`` until an environment adapter has implemented it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

SCHEMA_VERSION = 1

SemanticRelation = Literal[
    "semantically_equivalent",
    "epistemically_equivalent",
    "task_equivalent",
    "evaluator_changing",
    "task_changing",
]
InterventionKind = Literal[
    "observation",
    "presentation",
    "epistemic_event",
    "information_structure",
    "publicity_structure",
    "evidence",
    "truthful_selection",
    "signalling",
    "attention",
    "source_ecology",
    "evaluator",
    "evaluator_substitution",
    "measurement_adversary",
    "reward_proxy",
    "monitoring",
    "terminology",
    "tool_interface",
    "prior",
    "game_model",
    "strategic_depth",
    "custom",
]

_ALLOWED_RELATIONS = {
    "semantically_equivalent",
    "epistemically_equivalent",
    "task_equivalent",
    "evaluator_changing",
    "task_changing",
}
_ALLOWED_KINDS = {
    "observation",
    "presentation",
    "epistemic_event",
    "information_structure",
    "publicity_structure",
    "evidence",
    "truthful_selection",
    "signalling",
    "attention",
    "source_ecology",
    "evaluator",
    "evaluator_substitution",
    "measurement_adversary",
    "reward_proxy",
    "monitoring",
    "terminology",
    "tool_interface",
    "prior",
    "game_model",
    "strategic_depth",
    "custom",
}


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return {str(key): item for key, item in value.items()}


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list of strings")
    result = tuple(_text(item, f"{field_name}[{index}]") for index, item in enumerate(value))
    return result


@dataclass(frozen=True)
class LatentFactor:
    """A factor whose causal role is explicit even if an environment hides it."""

    factor_id: str
    role: Literal["task_state", "causal_mechanism", "observable_state", "proxy_signal", "evaluator_state", "hidden_state", "agent_belief", "custom"]
    description: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "LatentFactor":
        factor_id = _text(value.get("id", value.get("factor_id")), f"latent_factors[{index}].id")
        role = _text(value.get("role", "custom"), f"latent_factors[{index}].role")
        description = _text(value.get("description", factor_id), f"latent_factors[{index}].description")
        allowed = {"task_state", "causal_mechanism", "observable_state", "proxy_signal", "evaluator_state", "hidden_state", "agent_belief", "custom"}
        if role not in allowed:
            raise ValueError(f"latent_factors[{index}].role {role!r} is not supported")
        return cls(factor_id=factor_id, role=role, description=description)

    def as_dict(self) -> dict[str, str]:
        return {"id": self.factor_id, "role": self.role, "description": self.description}


@dataclass(frozen=True)
class Intervention:
    intervention_id: str
    kind: InterventionKind
    relation: SemanticRelation
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    materializer: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "Intervention":
        intervention_id = _text(value.get("id", value.get("intervention_id")), f"interventions[{index}].id")
        kind = _text(value.get("kind", "custom"), f"interventions[{index}].kind")
        relation = _text(value.get("relation", "task_equivalent"), f"interventions[{index}].relation")
        description = _text(value.get("description", intervention_id), f"interventions[{index}].description")
        if kind not in _ALLOWED_KINDS:
            raise ValueError(f"interventions[{index}].kind {kind!r} is not supported")
        if relation not in _ALLOWED_RELATIONS:
            raise ValueError(f"interventions[{index}].relation {relation!r} is not supported")
        materializer = value.get("materializer")
        if materializer is not None:
            materializer = _text(materializer, f"interventions[{index}].materializer")
        return cls(
            intervention_id=intervention_id,
            kind=kind,  # type: ignore[arg-type]
            relation=relation,  # type: ignore[arg-type]
            description=description,
            parameters=_mapping(value.get("parameters"), f"interventions[{index}].parameters"),
            materializer=materializer,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.intervention_id,
            "kind": self.kind,
            "relation": self.relation,
            "description": self.description,
            "parameters": dict(self.parameters),
            "materializer": self.materializer,
        }


@dataclass(frozen=True)
class PolicySpec:
    """Explicit environment/judge mechanism, not an inferred capability score."""

    policy_id: str
    role: Literal["observation_function", "reward_proxy", "evaluator_policy"]
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None, role: str) -> "PolicySpec":
        data = _mapping(value, f"experiment.{role}")
        policy_id = _text(data.get("id", role), f"experiment.{role}.id")
        description = _text(data.get("description", role), f"experiment.{role}.description")
        if role not in {"observation_function", "reward_proxy", "evaluator_policy"}:
            raise ValueError(f"unsupported policy role {role!r}")
        return cls(policy_id, role, description, _mapping(data.get("parameters"), f"experiment.{role}.parameters"))  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.policy_id,
            "role": self.role,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class Measurement:
    measurement_id: str
    metric: str
    description: str
    source: Literal["trajectory", "judge", "outcome", "derived"] = "derived"

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "Measurement":
        measurement_id = _text(value.get("id", value.get("measurement_id")), f"measurements[{index}].id")
        metric = _text(value.get("metric", measurement_id), f"measurements[{index}].metric")
        description = _text(value.get("description", metric), f"measurements[{index}].description")
        source = _text(value.get("source", "derived"), f"measurements[{index}].source")
        if source not in {"trajectory", "judge", "outcome", "derived"}:
            raise ValueError(f"measurements[{index}].source {source!r} is not supported")
        return cls(measurement_id, metric, description, source)  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.measurement_id,
            "metric": self.metric,
            "description": self.description,
            "source": self.source,
        }


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    title: str
    hypothesis: str
    base_environment: str
    latent_factors: tuple[LatentFactor, ...]
    interventions: tuple[Intervention, ...]
    measurements: tuple[Measurement, ...]
    expected_invariances: tuple[str, ...] = ()
    expected_differences: tuple[str, ...] = ()
    controls: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    design_only: bool = True
    schema_version: int = SCHEMA_VERSION
    capability_requirements: tuple[str, ...] = ()
    difficulty_axes: tuple[str, ...] = ()
    observation_function: PolicySpec = field(
        default_factory=lambda: PolicySpec("observation_function", "observation_function", "Declared observation mapping")
    )
    reward_proxy: PolicySpec = field(
        default_factory=lambda: PolicySpec("reward_proxy", "reward_proxy", "Declared reward/proxy mapping")
    )
    evaluator_policy: PolicySpec = field(
        default_factory=lambda: PolicySpec("evaluator_policy", "evaluator_policy", "Declared evaluator state and judgment")
    )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperimentSpec":
        experiment_id = _text(value.get("id", value.get("experiment_id")), "experiment.id")
        title = _text(value.get("title", experiment_id), "experiment.title")
        hypothesis = _text(value.get("hypothesis"), "experiment.hypothesis")
        base_environment = _text(value.get("base_environment"), "experiment.base_environment")
        latent_values = value.get("latent_factors", [])
        intervention_values = value.get("interventions", [])
        measurement_values = value.get("measurements", [])
        if not isinstance(latent_values, list):
            raise ValueError("experiment.latent_factors must be a list")
        if not isinstance(intervention_values, list) or not intervention_values:
            raise ValueError("experiment.interventions must be a non-empty list")
        if not isinstance(measurement_values, list) or not measurement_values:
            raise ValueError("experiment.measurements must be a non-empty list")
        latent_factors = tuple(
            LatentFactor.from_dict(item, index)
            for index, item in enumerate(latent_values)
            if isinstance(item, Mapping)
        )
        interventions = tuple(
            Intervention.from_dict(item, index)
            for index, item in enumerate(intervention_values)
            if isinstance(item, Mapping)
        )
        measurements = tuple(
            Measurement.from_dict(item, index)
            for index, item in enumerate(measurement_values)
            if isinstance(item, Mapping)
        )
        if len(latent_factors) != len(latent_values):
            raise ValueError("every latent factor must be an object")
        if len(interventions) != len(intervention_values):
            raise ValueError("every intervention must be an object")
        if len(measurements) != len(measurement_values):
            raise ValueError("every measurement must be an object")
        spec = cls(
            experiment_id=experiment_id,
            title=title,
            hypothesis=hypothesis,
            base_environment=base_environment,
            latent_factors=latent_factors,
            interventions=interventions,
            measurements=measurements,
            capability_requirements=_string_tuple(value.get("capability_requirements"), "experiment.capability_requirements"),
            difficulty_axes=_string_tuple(value.get("difficulty_axes"), "experiment.difficulty_axes"),
            expected_invariances=_string_tuple(value.get("expected_invariances"), "experiment.expected_invariances"),
            expected_differences=_string_tuple(value.get("expected_differences"), "experiment.expected_differences"),
            controls=_string_tuple(value.get("controls"), "experiment.controls"),
            provenance=_mapping(value.get("provenance"), "experiment.provenance"),
            design_only=bool(value.get("design_only", True)),
            observation_function=PolicySpec.from_dict(value.get("observation_function"), "observation_function"),
            reward_proxy=PolicySpec.from_dict(value.get("reward_proxy"), "reward_proxy"),
            evaluator_policy=PolicySpec.from_dict(value.get("evaluator_policy"), "evaluator_policy"),
            schema_version=int(value.get("schema_version", SCHEMA_VERSION)),
        )
        spec.validate()
        return spec

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported experiment schema_version {self.schema_version}")
        ids = [factor.factor_id for factor in self.latent_factors]
        if len(ids) != len(set(ids)):
            raise ValueError("latent factor ids must be unique")
        intervention_ids = [item.intervention_id for item in self.interventions]
        if len(intervention_ids) != len(set(intervention_ids)):
            raise ValueError("intervention ids must be unique")
        measurement_ids = [item.measurement_id for item in self.measurements]
        if len(measurement_ids) != len(set(measurement_ids)):
            raise ValueError("measurement ids must be unique")
        if not any(item.role == "task_state" for item in self.latent_factors):
            raise ValueError("experiment must declare a task_state latent factor")
        if not any(item.role == "evaluator_state" for item in self.latent_factors):
            raise ValueError("experiment must declare an evaluator_state latent factor")
        if not self.controls:
            raise ValueError("experiment must declare at least one control")
        intervention_set = set(intervention_ids)
        for field_name, values in (
            ("expected_invariances", self.expected_invariances),
            ("expected_differences", self.expected_differences),
        ):
            unknown = sorted(set(values) - intervention_set)
            if unknown:
                raise ValueError(f"{field_name} references unknown interventions: {unknown}")
        overlap = sorted(set(self.expected_invariances) & set(self.expected_differences))
        if overlap:
            raise ValueError(f"interventions cannot be both invariant and different: {overlap}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.experiment_id,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "base_environment": self.base_environment,
            "latent_factors": [item.as_dict() for item in self.latent_factors],
            "interventions": [item.as_dict() for item in self.interventions],
            "measurements": [item.as_dict() for item in self.measurements],
            "capability_requirements": list(self.capability_requirements),
            "difficulty_axes": list(self.difficulty_axes),
            "expected_invariances": list(self.expected_invariances),
            "expected_differences": list(self.expected_differences),
            "controls": list(self.controls),
            "provenance": dict(self.provenance),
            "design_only": self.design_only,
            "observation_function": self.observation_function.as_dict(),
            "reward_proxy": self.reward_proxy.as_dict(),
            "evaluator_policy": self.evaluator_policy.as_dict(),
        }

    def digest(self) -> str:
        encoded = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def expand_counterfactual_twins(
    spec: ExperimentSpec,
    base_cases: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Create baseline/intervention metadata without claiming materialization.

    Each base case becomes one twin group.  The intervention variants retain
    the same environment, difficulty, and seed; an environment adapter must
    later apply the declared intervention before the group is schedulable.
    """

    spec.validate()
    expanded: list[dict[str, Any]] = []
    for base in base_cases:
        base_id = _text(base.get("case_id"), "base_case.case_id")
        twin_group = f"{spec.experiment_id}:{base_id}"
        variants = [("baseline", None), *[(item.intervention_id, item) for item in spec.interventions]]
        ids = {variant_id: f"{base_id}__experiment-{_safe_id(spec.experiment_id)}__variant-{_safe_id(variant_id)}" for variant_id, _ in variants}
        for variant_id, intervention in variants:
            relation = "semantically_equivalent" if intervention is None else intervention.relation
            row = dict(base)
            row.update(
                {
                    "case_id": ids[variant_id],
                    "base_case_id": base_id,
                    "experiment_id": spec.experiment_id,
                    "experiment_spec_sha256": spec.digest(),
                    "variant_id": variant_id,
                    "twin_group_id": twin_group,
                    "counterfactual_partner_ids": [value for key, value in ids.items() if key != variant_id],
                    "intervention": intervention.as_dict() if intervention else None,
                    "expected_relation": relation,
                    "experiment_materialized": bool(intervention is None or intervention.materializer),
                    "experiment_design_only": spec.design_only,
                    "hypothesis": spec.hypothesis,
                    "capability_requirements": list(spec.capability_requirements),
                    "difficulty_axes": list(spec.difficulty_axes),
                    "difficulty_vector": base.get("difficulty_levels", base.get("difficulty")),
                    "measurement_ids": [item.measurement_id for item in spec.measurements],
                    "expected_invariances": list(spec.expected_invariances),
                    "expected_differences": list(spec.expected_differences),
                }
            )
            expanded.append(row)
    return expanded


__all__ = [
    "ExperimentSpec",
    "Intervention",
    "LatentFactor",
    "Measurement",
    "PolicySpec",
    "SCHEMA_VERSION",
    "expand_counterfactual_twins",
]
