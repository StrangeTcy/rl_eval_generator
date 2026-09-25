"""Canonical finite relay-machine schema used by direct and generated judges."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PayloadOp = Literal["identity", "flip", "constant"]
State = tuple[str, int]
ConcreteTransition = tuple[str, PayloadOp, int | None]


@dataclass(frozen=True)
class RelayRule:
    source: str
    target: str
    payload_op: PayloadOp
    constant: int | None = None

    def apply(self, payload: int) -> int:
        if self.payload_op == "identity":
            return payload
        if self.payload_op == "flip":
            return 1 - payload
        if self.payload_op == "constant" and self.constant in (0, 1):
            return self.constant
        raise ValueError(f"invalid payload operation: {self}")


@dataclass(frozen=True)
class RelaySystem:
    templates: tuple[str, ...]
    payload_domain: tuple[int, ...]
    rules: tuple[RelayRule, ...]
    system_id: str = "relay"

    def __post_init__(self) -> None:
        if not self.templates:
            raise ValueError("a relay must have at least one template")
        if self.payload_domain != (0, 1):
            raise ValueError("the V1 relay payload domain must be (0, 1)")
        if len(self.rules) != len(self.templates) or {rule.source for rule in self.rules} != set(self.templates):
            raise ValueError("there must be exactly one rule for every template")
        if any(rule.target not in self.templates for rule in self.rules):
            raise ValueError("rule target is not a template")
        if any(rule.payload_op == "constant" and rule.constant not in (0, 1) for rule in self.rules):
            raise ValueError("constant rules must use payload 0 or 1")

    def rule_for(self, template: str) -> RelayRule:
        for rule in self.rules:
            if rule.source == template:
                return rule
        raise KeyError(template)

    def transition(self, state: State) -> State:
        template, payload = state
        if template not in self.templates or payload not in self.payload_domain:
            raise ValueError(f"state is not in system: {state}")
        rule = self.rule_for(template)
        return rule.target, rule.apply(payload)


@dataclass(frozen=True)
class SurfaceMapping:
    """A bijection from canonical templates/payloads to rendered labels."""

    templates: dict[str, str]
    payloads: dict[int, str]
    relabeling: str

    def inverse_template(self) -> dict[str, str]:
        return {value: key for key, value in self.templates.items()}

    def inverse_payload(self) -> dict[str, int]:
        return {value: key for key, value in self.payloads.items()}


@dataclass(frozen=True)
class ParsedRelay:
    """A rendered relay parsed without evaluating source code.

    ``system`` is retained as the structural AST used to validate declarations.
    ``transitions`` is a separate concrete transition dictionary used by the
    rendered executor, so concrete rollout does not call abstract rule methods.
    """

    system: RelaySystem
    payload_labels: dict[int, str]
    presentation: str
    transitions: dict[str, ConcreteTransition] = field(default_factory=dict)

    def state_from_rendered(self, text: str) -> State:
        from .rendered_parser import parse_state

        return parse_state(text, self.system, self.payload_labels)

    def concrete_transition(self, state: State) -> State:
        template, payload = state
        if template not in self.system.templates or payload not in self.system.payload_domain:
            raise ValueError(f"state is not in parsed system: {state}")
        try:
            target, operation, constant = self.transitions[template]
        except KeyError as exc:
            raise ValueError(f"missing concrete transition for {template}") from exc
        if operation == "identity":
            next_payload = payload
        elif operation == "flip":
            next_payload = 1 - payload
        elif operation == "constant" and constant in (0, 1):
            next_payload = constant
        else:
            raise ValueError(f"invalid concrete transition for {template}")
        return target, next_payload


@dataclass(frozen=True)
class OrbitMetadata:
    transient_length: int
    cycle_length: int
    cycle_start: State

    def as_dict(self) -> dict[str, object]:
        return {
            "transient_length": self.transient_length,
            "cycle_length": self.cycle_length,
            "cycle_start": {"template": self.cycle_start[0], "payload": self.cycle_start[1]},
        }
