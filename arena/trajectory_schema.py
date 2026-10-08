"""Canonical, model-independent trajectory events and derived diagnostics.

The schema is intentionally observational.  A field named ``belief`` or
``hypothesis`` is evidence emitted by an environment/controller, never a claim
about hidden model state.  This keeps trajectory measurements useful across
coding, epistemic, ML, and trajectory-semantics environments without
reifying unobserved cognition.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = 1
EVENT_TYPES = {
    "observation",
    "action",
    "tool_call",
    "file_mutation",
    "test_execution",
    "intermediate_result",
    "belief_relevant_observation",
    "reward",
    "termination",
    "announcement",
    "information_delivery",
    "acknowledgement",
    "hypothesis_update",
    "belief_update",
    "reward_proxy_evaluation",
    "judge_observation",
}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CanonicalEvent:
    sequence: int
    event_type: str
    payload: dict[str, Any]
    source: str = "controller"
    turn: int | None = None
    causal_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("event sequence must be non-negative")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported canonical event type: {self.event_type}")
        if not isinstance(self.payload, dict):
            raise ValueError("event payload must be an object")

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload": {str(key): _jsonable(value) for key, value in self.payload.items()},
            "source": self.source,
            "turn": self.turn,
            "causal_tags": list(self.causal_tags),
        }


@dataclass
class CanonicalTrajectory:
    run_id: str | None
    case_id: str | None
    events: list[CanonicalEvent] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def append(self, event: CanonicalEvent) -> None:
        if self.events and event.sequence <= self.events[-1].sequence:
            raise ValueError("trajectory event sequences must increase")
        self.events.append(event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "events": [event.as_dict() for event in self.events],
            "metrics": self.metrics(),
        }

    def metrics(self) -> dict[str, Any]:
        actions = [event for event in self.events if event.event_type == "action"]
        action_labels = [
            str(event.payload.get("action_type", event.payload.get("action", "unknown")))
            for event in actions
        ]
        tool_events = [event for event in self.events if event.event_type == "tool_call"]
        hypotheses = [
            event.payload.get("hypothesis")
            for event in self.events
            if event.payload.get("hypothesis") is not None
        ]
        states = [
            event.payload.get("state_fingerprint")
            for event in self.events
            if event.payload.get("state_fingerprint") is not None
        ]
        return {
            "event_count": len(self.events),
            "action_count": len(actions),
            "tool_call_count": len(tool_events),
            "action_entropy": _entropy(action_labels),
            "repeated_action_rate": _repeated_rate(action_labels),
            "backtracking_count": _backtracking_count(action_labels),
            "hypothesis_switch_count": _switch_count(hypotheses),
            "state_revisitation_count": _revisitation_count(states),
            "time_to_first_discriminating_test": _first_discriminating_test(self.events),
            "proxy_exploitation_count": sum(
                1
                for event in self.events
                if event.payload.get("proxy_exploited") is True
                or (
                    event.event_type == "reward_proxy_evaluation"
                    and event.payload.get("exploited") is True
                )
            ),
            "information_gain_total": sum(
                float(event.payload.get("information_gain", 0.0))
                for event in self.events
                if isinstance(event.payload.get("information_gain", 0.0), (int, float))
            ),
        }


def _entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return round(-sum((count / total) * math.log2(count / total) for count in counts.values()), 6)


def _repeated_rate(values: list[str]) -> float:
    if len(values) < 2:
        return 0.0
    return round(sum(left == right for left, right in zip(values, values[1:])) / (len(values) - 1), 6)


def _switch_count(values: list[Any]) -> int:
    if len(values) < 2:
        return 0
    return sum(left != right for left, right in zip(values, values[1:]))


def _backtracking_count(values: list[str]) -> int:
    seen: set[str] = set()
    count = 0
    for value in values:
        if value in seen:
            count += 1
        seen.add(value)
    return count


def _revisitation_count(values: list[Any]) -> int:
    if not values:
        return 0
    return len(values) - len(set(values))


def _first_discriminating_test(events: list[CanonicalEvent]) -> int | None:
    for index, event in enumerate(events):
        if event.event_type in {"tool_call", "test_execution"} and (
            event.payload.get("discriminating") is True
            or event.payload.get("information_gain", 0) not in {0, 0.0, None}
        ):
            return index
    return None


def canonicalize_trace(
    records: list[Mapping[str, Any]], *, run_id: str | None = None, case_id: str | None = None
) -> CanonicalTrajectory:
    """Normalize current arena trace rows into the cross-environment schema."""

    trajectory = CanonicalTrajectory(run_id=run_id, case_id=case_id)
    sequence = 0
    for row in records:
        turn = row.get("turn") if isinstance(row.get("turn"), int) else None
        observation = row.get("environment_observation")
        if observation not in (None, ""):
            trajectory.append(
                CanonicalEvent(
                    sequence,
                    "observation",
                    {
                        "text": str(observation),
                        "reward": row.get("reward"),
                        "done": row.get("done"),
                        "state_fingerprint": _fingerprint(row.get("environment_info", {})),
                    },
                    turn=turn,
                )
            )
            sequence += 1
        action = row.get("parsed_action")
        if isinstance(action, Mapping):
            trajectory.append(
                CanonicalEvent(
                    sequence,
                    "action",
                    {
                        "action_type": action.get("type", action.get("cmd", "unknown")),
                        "action": dict(action),
                        "raw_model_output": row.get("raw_model_output", ""),
                        "hypothesis": row.get("hypothesis"),
                    },
                    source="model",
                    turn=turn,
                )
            )
            sequence += 1
        info = row.get("environment_info")
        if isinstance(info, Mapping):
            stream = info.get("events", info.get("event_stream", []))
            if isinstance(stream, list):
                for raw_event in stream:
                    if not isinstance(raw_event, Mapping):
                        continue
                    declared_type = str(raw_event.get("event_type", raw_event.get("type", "intermediate_result")))
                    event_type = declared_type if declared_type in EVENT_TYPES else "intermediate_result"
                    trajectory.append(
                        CanonicalEvent(sequence, event_type, dict(raw_event), source="environment", turn=turn)
                    )
                    sequence += 1
            for key, event_type in (
                ("tool_call", "tool_call"),
                ("file_mutation", "file_mutation"),
                ("test_execution", "test_execution"),
            ):
                value = info.get(key)
                if value is not None:
                    trajectory.append(CanonicalEvent(sequence, event_type, {key: value}, turn=turn))
                    sequence += 1
        if "reward" in row:
            trajectory.append(
                CanonicalEvent(sequence, "reward", {"value": row.get("reward"), "done": row.get("done")}, turn=turn)
            )
            sequence += 1
        if row.get("done") is True:
            trajectory.append(
                CanonicalEvent(
                    sequence,
                    "termination",
                    {"reward": row.get("reward"), "failure": info.get("failure") if isinstance(info, Mapping) else None},
                    turn=turn,
                )
            )
            sequence += 1
    return trajectory


__all__ = [
    "CanonicalEvent",
    "CanonicalTrajectory",
    "EVENT_TYPES",
    "SCHEMA_VERSION",
    "canonicalize_trace",
]
