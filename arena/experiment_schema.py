"""Typed, provider-free schema for causal experiment families.

The ordinary suite manifest describes *which task* to run.  This module adds a
separate design layer describing what is being intervened on, which variants are
counterfactual twins, and which behavioral relations are expected.  It does not
pretend that metadata alone materializes an intervention: a family remains
``design_only`` until an environment adapter has implemented it.
"""
from __future__ import annotations

import hashlib
import itertools
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
class EpistemicEventSpec:
    """An information-delivery event, separate from the hidden world state."""

    event_id: str
    event_type: Literal["announcement", "message", "observation", "acknowledgement"]
    publicity: Literal["public", "private", "asymmetric", "public_uncertain"]
    delivery_uncertainty: bool = False
    acknowledgement: bool = False
    common_knowledge: bool = False
    sender: str | None = None
    recipients: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    materializer: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "EpistemicEventSpec":
        event_id = _text(value.get("id", value.get("event_id")), f"epistemic_events[{index}].id")
        event_type = _text(value.get("event_type", "announcement"), f"epistemic_events[{index}].event_type")
        publicity = _text(value.get("publicity", "public"), f"epistemic_events[{index}].publicity")
        if event_type not in {"announcement", "message", "observation", "acknowledgement"}:
            raise ValueError(f"epistemic_events[{index}].event_type {event_type!r} is not supported")
        if publicity not in {"public", "private", "asymmetric", "public_uncertain"}:
            raise ValueError(f"epistemic_events[{index}].publicity {publicity!r} is not supported")
        delivery_uncertainty = bool(value.get("delivery_uncertainty", publicity == "public_uncertain"))
        acknowledgement = bool(value.get("acknowledgement", False))
        common_knowledge = bool(value.get("common_knowledge", False))
        if common_knowledge and publicity not in {"public", "public_uncertain"}:
            raise ValueError("common knowledge requires a public event structure")
        recipients = value.get("recipients", [])
        if not isinstance(recipients, list) or any(not isinstance(item, str) or not item.strip() for item in recipients):
            raise ValueError(f"epistemic_events[{index}].recipients must be a list of strings")
        sender = value.get("sender")
        if sender is not None:
            sender = _text(sender, f"epistemic_events[{index}].sender")
        materializer = value.get("materializer")
        if materializer is not None:
            materializer = _text(materializer, f"epistemic_events[{index}].materializer")
        return cls(
            event_id=event_id,
            event_type=event_type,  # type: ignore[arg-type]
            publicity=publicity,  # type: ignore[arg-type]
            delivery_uncertainty=delivery_uncertainty,
            acknowledgement=acknowledgement,
            common_knowledge=common_knowledge,
            sender=sender,
            recipients=tuple(recipients),
            parameters=_mapping(value.get("parameters"), f"epistemic_events[{index}].parameters"),
            materializer=materializer,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "event_type": self.event_type,
            "publicity": self.publicity,
            "delivery_uncertainty": self.delivery_uncertainty,
            "acknowledgement": self.acknowledgement,
            "common_knowledge": self.common_knowledge,
            "sender": self.sender,
            "recipients": list(self.recipients),
            "parameters": dict(self.parameters),
            "materializer": self.materializer,
        }


@dataclass(frozen=True)
class GameModelSpec:
    """A game representation held by one agent; hypergames need not agree."""

    model_id: str
    players: tuple[str, ...]
    actions: tuple[str, ...]
    objectives: dict[str, str] = field(default_factory=dict)
    observation_rules: dict[str, Any] = field(default_factory=dict)
    materializer: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "GameModelSpec":
        model_id = _text(value.get("id", value.get("model_id")), f"game_models[{index}].id")
        players = _string_tuple(value.get("players"), f"game_models[{index}].players")
        actions = _string_tuple(value.get("actions"), f"game_models[{index}].actions")
        if not players:
            raise ValueError(f"game_models[{index}].players must not be empty")
        if not actions:
            raise ValueError(f"game_models[{index}].actions must not be empty")
        objectives = _mapping(value.get("objectives"), f"game_models[{index}].objectives")
        if any(not isinstance(key, str) or not isinstance(item, str) for key, item in objectives.items()):
            raise ValueError(f"game_models[{index}].objectives must map agent IDs to strings")
        materializer = value.get("materializer")
        if materializer is not None:
            materializer = _text(materializer, f"game_models[{index}].materializer")
        return cls(
            model_id=model_id,
            players=players,
            actions=actions,
            objectives={str(key): str(item) for key, item in objectives.items()},
            observation_rules=_mapping(value.get("observation_rules"), f"game_models[{index}].observation_rules"),
            materializer=materializer,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.model_id,
            "players": list(self.players),
            "actions": list(self.actions),
            "objectives": dict(self.objectives),
            "observation_rules": dict(self.observation_rules),
            "materializer": self.materializer,
        }


@dataclass(frozen=True)
class StrategicProfileSpec:
    """Agent-specific strategic depth and beliefs about opponent depth."""

    profile_id: str
    agent_id: str
    game_model_id: str
    level_k: int
    opponent_depth_beliefs: dict[str, int] = field(default_factory=dict)
    opponent_model_ids: dict[str, str] = field(default_factory=dict)
    materializer: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "StrategicProfileSpec":
        profile_id = _text(value.get("id", value.get("profile_id")), f"strategic_profiles[{index}].id")
        agent_id = _text(value.get("agent_id"), f"strategic_profiles[{index}].agent_id")
        game_model_id = _text(value.get("game_model_id"), f"strategic_profiles[{index}].game_model_id")
        level_k = value.get("level_k")
        if not isinstance(level_k, int) or isinstance(level_k, bool) or level_k < 0:
            raise ValueError(f"strategic_profiles[{index}].level_k must be a non-negative integer")
        beliefs_raw = _mapping(value.get("opponent_depth_beliefs"), f"strategic_profiles[{index}].opponent_depth_beliefs")
        if any(not isinstance(key, str) or not isinstance(item, int) or isinstance(item, bool) or item < 0 for key, item in beliefs_raw.items()):
            raise ValueError(f"strategic_profiles[{index}].opponent_depth_beliefs must map IDs to non-negative integers")
        models_raw = _mapping(value.get("opponent_model_ids"), f"strategic_profiles[{index}].opponent_model_ids")
        if any(not isinstance(key, str) or not isinstance(item, str) or not item.strip() for key, item in models_raw.items()):
            raise ValueError(f"strategic_profiles[{index}].opponent_model_ids must map IDs to strings")
        materializer = value.get("materializer")
        if materializer is not None:
            materializer = _text(materializer, f"strategic_profiles[{index}].materializer")
        return cls(
            profile_id=profile_id,
            agent_id=agent_id,
            game_model_id=game_model_id,
            level_k=level_k,
            opponent_depth_beliefs={str(key): int(item) for key, item in beliefs_raw.items()},
            opponent_model_ids={str(key): str(item) for key, item in models_raw.items()},
            materializer=materializer,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "agent_id": self.agent_id,
            "game_model_id": self.game_model_id,
            "level_k": self.level_k,
            "opponent_depth_beliefs": dict(self.opponent_depth_beliefs),
            "opponent_model_ids": dict(self.opponent_model_ids),
            "materializer": self.materializer,
        }


@dataclass(frozen=True)
class InformationEnvironmentSpec:
    """Multi-step information ecology and attention policy."""

    environment_id: str
    horizon: int
    observation_mode: Literal["static", "sequential", "adaptive"]
    source_ecology: Literal["single", "independent", "coordinated", "partially_coordinated", "adversarial"]
    signal_policy: Literal["truthful", "selected_truthful", "state_contingent", "strategic"]
    attention_mode: Literal["fixed", "endogenous"]
    negative_information: bool = False
    belief_trajectory: bool = True
    state_contingent_signalling: bool = False
    steps: tuple[dict[str, Any], ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    materializer: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int = 0) -> "InformationEnvironmentSpec":
        environment_id = _text(value.get("id", value.get("environment_id")), f"information_environments[{index}].id")
        horizon = value.get("horizon", 1)
        if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
            raise ValueError(f"information_environments[{index}].horizon must be a positive integer")
        observation_mode = _text(value.get("observation_mode", "static"), f"information_environments[{index}].observation_mode")
        source_ecology = _text(value.get("source_ecology", "single"), f"information_environments[{index}].source_ecology")
        signal_policy = _text(value.get("signal_policy", "truthful"), f"information_environments[{index}].signal_policy")
        attention_mode = _text(value.get("attention_mode", "fixed"), f"information_environments[{index}].attention_mode")
        if observation_mode not in {"static", "sequential", "adaptive"}:
            raise ValueError(f"information_environments[{index}].observation_mode is not supported")
        if source_ecology not in {"single", "independent", "coordinated", "partially_coordinated", "adversarial"}:
            raise ValueError(f"information_environments[{index}].source_ecology is not supported")
        if signal_policy not in {"truthful", "selected_truthful", "state_contingent", "strategic"}:
            raise ValueError(f"information_environments[{index}].signal_policy is not supported")
        if attention_mode not in {"fixed", "endogenous"}:
            raise ValueError(f"information_environments[{index}].attention_mode is not supported")
        state_contingent = bool(value.get("state_contingent_signalling", signal_policy in {"state_contingent", "strategic"}))
        if state_contingent and observation_mode == "static" and horizon > 1:
            raise ValueError("state-contingent signalling with horizon > 1 must use sequential or adaptive observations")
        steps_raw = value.get("steps", [])
        if not isinstance(steps_raw, list):
            raise ValueError(f"information_environments[{index}].steps must be a list")
        steps: list[dict[str, Any]] = []
        for step_index, step in enumerate(steps_raw):
            if not isinstance(step, Mapping):
                raise ValueError(f"information_environments[{index}].steps[{step_index}] must be an object")
            normalized = _mapping(step, f"information_environments[{index}].steps[{step_index}]")
            _text(normalized.get("id", normalized.get("step_id")), f"information_environments[{index}].steps[{step_index}].id")
            _text(normalized.get("trigger", "after_observation"), f"information_environments[{index}].steps[{step_index}].trigger")
            steps.append(normalized)
        if steps and len(steps) > horizon:
            raise ValueError(f"information_environments[{index}].steps cannot exceed horizon")
        materializer = value.get("materializer")
        if materializer is not None:
            materializer = _text(materializer, f"information_environments[{index}].materializer")
        return cls(
            environment_id=environment_id,
            horizon=horizon,
            observation_mode=observation_mode,  # type: ignore[arg-type]
            source_ecology=source_ecology,  # type: ignore[arg-type]
            signal_policy=signal_policy,  # type: ignore[arg-type]
            attention_mode=attention_mode,  # type: ignore[arg-type]
            negative_information=bool(value.get("negative_information", False)),
            belief_trajectory=bool(value.get("belief_trajectory", horizon > 1)),
            state_contingent_signalling=state_contingent,
            steps=tuple(steps),
            parameters=_mapping(value.get("parameters"), f"information_environments[{index}].parameters"),
            materializer=materializer,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.environment_id,
            "horizon": self.horizon,
            "observation_mode": self.observation_mode,
            "source_ecology": self.source_ecology,
            "signal_policy": self.signal_policy,
            "attention_mode": self.attention_mode,
            "negative_information": self.negative_information,
            "belief_trajectory": self.belief_trajectory,
            "state_contingent_signalling": self.state_contingent_signalling,
            "steps": [dict(step) for step in self.steps],
            "parameters": dict(self.parameters),
            "materializer": self.materializer,
        }


@dataclass(frozen=True)
class CausalBasisAxes:
    """Independent basis vectors crossed into controlled experimental cells."""

    epistemic_events: tuple[EpistemicEventSpec, ...] = ()
    game_models: tuple[GameModelSpec, ...] = ()
    strategic_profiles: tuple[StrategicProfileSpec, ...] = ()
    information_environments: tuple[InformationEnvironmentSpec, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "CausalBasisAxes":
        data = _mapping(value, "experiment.basis_axes")
        def parse_list(key: str, parser: Any) -> tuple[Any, ...]:
            raw = data.get(key, [])
            if not isinstance(raw, list):
                raise ValueError(f"experiment.basis_axes.{key} must be a list")
            return tuple(parser(item, index) for index, item in enumerate(raw) if isinstance(item, Mapping))
        axes = cls(
            epistemic_events=parse_list("epistemic_events", EpistemicEventSpec.from_dict),
            game_models=parse_list("game_models", GameModelSpec.from_dict),
            strategic_profiles=parse_list("strategic_profiles", StrategicProfileSpec.from_dict),
            information_environments=parse_list("information_environments", InformationEnvironmentSpec.from_dict),
        )
        for key in ("epistemic_events", "game_models", "strategic_profiles", "information_environments"):
            raw = data.get(key, [])
            parsed = getattr(axes, key)
            if len(parsed) != len(raw):
                raise ValueError(f"every experiment.basis_axes.{key} item must be an object")
        axes.validate()
        return axes

    def validate(self) -> None:
        for field_name in ("epistemic_events", "game_models", "strategic_profiles", "information_environments"):
            values = getattr(self, field_name)
            ids = [getattr(item, "event_id", getattr(item, "model_id", getattr(item, "profile_id", getattr(item, "environment_id", "")))) for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"experiment.basis_axes.{field_name} ids must be unique")
        model_ids = {item.model_id for item in self.game_models}
        for profile in self.strategic_profiles:
            if profile.game_model_id not in model_ids:
                raise ValueError(f"strategic profile {profile.profile_id!r} references unknown game model {profile.game_model_id!r}")

    def cells(self) -> list[dict[str, Any]]:
        """Return the explicit crossed product, or one empty cell if unused."""
        axes: list[tuple[str, list[Any]]] = [
            ("epistemic_event", list(self.epistemic_events) or [None]),
            (
                "strategic_profile" if self.strategic_profiles else "game_model",
                list(self.strategic_profiles) or list(self.game_models) or [None],
            ),
            ("information_environment", list(self.information_environments) or [None]),
        ]
        cells: list[dict[str, Any]] = []
        models = {item.model_id: item for item in self.game_models}
        for values in itertools.product(*(items for _, items in axes)):
            cell: dict[str, Any] = {}
            for (axis_id, _), value in zip(axes, values):
                if value is not None:
                    cell[axis_id] = value
                    if axis_id == "strategic_profile":
                        cell["game_model"] = models[value.game_model_id]
            cells.append(cell)
        return cells

    @staticmethod
    def cell_id(cell: Mapping[str, Any]) -> str:
        parts = []
        for key in ("epistemic_event", "game_model", "strategic_profile", "information_environment"):
            value = cell.get(key)
            if value is None:
                continue
            identifier = getattr(value, "event_id", getattr(value, "model_id", getattr(value, "profile_id", getattr(value, "environment_id", "unknown"))))
            parts.append(f"{key}-{_safe_id(identifier)}")
        return "__".join(parts) or "baseline"

    @staticmethod
    def cell_as_dict(cell: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {"cell_id": CausalBasisAxes.cell_id(cell)}
        for key, value in cell.items():
            result[key] = value.as_dict() if hasattr(value, "as_dict") else value
        return result


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
    basis_axes: CausalBasisAxes = field(default_factory=CausalBasisAxes)

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
            basis_axes=CausalBasisAxes.from_dict(value.get("basis_axes")),
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
        self.basis_axes.validate()
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
            "basis_axes": {
                "epistemic_events": [item.as_dict() for item in self.basis_axes.epistemic_events],
                "game_models": [item.as_dict() for item in self.basis_axes.game_models],
                "strategic_profiles": [item.as_dict() for item in self.basis_axes.strategic_profiles],
                "information_environments": [item.as_dict() for item in self.basis_axes.information_environments],
            },
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
        for cell in spec.basis_axes.cells():
            basis_cell_id = spec.basis_axes.cell_id(cell)
            twin_group = f"{spec.experiment_id}:{base_id}:basis-{basis_cell_id}"
            variants = [("baseline", None), *[(item.intervention_id, item) for item in spec.interventions]]
            ids = {
                variant_id: (
                    f"{base_id}__experiment-{_safe_id(spec.experiment_id)}"
                    f"__basis-{_safe_id(basis_cell_id)}__variant-{_safe_id(variant_id)}"
                )
                for variant_id, _ in variants
            }
            basis_materialized = all(
                getattr(value, "materializer", None)
                for value in cell.values()
                if hasattr(value, "as_dict")
            )
            # An empty basis is the backwards-compatible baseline and needs no
            # adapter. Once a basis vector is declared, every selected cell
            # must name a materializer before it can be scheduled.
            if not cell:
                basis_materialized = True
            basis_metadata = spec.basis_axes.cell_as_dict(cell)
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
                        "basis_cell_id": basis_cell_id,
                        "basis_cell": basis_metadata,
                        "counterfactual_partner_ids": [value for key, value in ids.items() if key != variant_id],
                        "intervention_id": intervention.intervention_id if intervention else None,
                        "intervention": intervention.as_dict() if intervention else None,
                        "expected_relation": relation,
                        "experiment_materialized": bool(
                            basis_materialized and (intervention is None or intervention.materializer)
                        ),
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
    "CausalBasisAxes",
    "EpistemicEventSpec",
    "ExperimentSpec",
    "GameModelSpec",
    "InformationEnvironmentSpec",
    "Intervention",
    "LatentFactor",
    "Measurement",
    "PolicySpec",
    "StrategicProfileSpec",
    "SCHEMA_VERSION",
    "expand_counterfactual_twins",
]
