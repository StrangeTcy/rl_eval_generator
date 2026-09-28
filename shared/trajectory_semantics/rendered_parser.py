"""Parser/interpreter for the flat and restricted reflective relay DSL."""
from __future__ import annotations

import re

from .schema import ConcreteTransition, ParsedRelay, RelayRule, RelaySystem, State

_STATE_RE = re.compile(r"^\s*([^()\s]+)\(([^()]+)\)\s*$")
_FLAT_RULE_RE = re.compile(
    r"^-\s+([^()\s]+)\(payload\)\s*->\s*([^()\s]+)\((.+)\)\s*$"
)
_REF_TEMPLATE_RE = re.compile(r"^template\s+([^()\s]+)\(payload\):\s*$")
_REF_EMIT_RE = re.compile(r'^\s*emit_source\("([^()\s]+)\((.+)\)"\)\s*$')
_SYSTEM_RE = re.compile(r"^system:\s*(\S+)\s*$", re.M)


def _system_id(text: str) -> str:
    match = _SYSTEM_RE.search(text)
    return match.group(1) if match else "parsed-relay"


def _payload_labels(text: str) -> dict[str, int]:
    match = re.search(r"^payloads:\s*([^,]+),\s*(.+)$", text, re.M)
    if not match:
        raise ValueError("payloads declaration missing")
    first, second = match.group(1).strip(), match.group(2).strip()
    if first == second:
        raise ValueError("payload labels must be distinct")
    return {first: 0, second: 1}


def parse_state(text: str, system: RelaySystem, payload_labels: dict[int, str]) -> State:
    match = _STATE_RE.match(text)
    if not match:
        raise ValueError(f"invalid rendered state: {text!r}")
    template, payload_label = match.group(1), match.group(2).strip()
    inverse = {value: key for key, value in payload_labels.items()}
    if template not in system.templates or payload_label not in inverse:
        raise ValueError(f"state is not in parsed system: {text!r}")
    return template, inverse[payload_label]


def _op_from_expr(expression: str, target: str, payload_inverse: dict[str, int]) -> tuple[str, int | None]:
    expression = expression.strip()
    if expression == "payload":
        return "identity", None
    if expression == "flip(payload)":
        return "flip", None
    if expression in payload_inverse:
        return "constant", payload_inverse[expression]
    raise ValueError(f"unknown payload expression: {expression!r} for {target}")


def parse_rendered(text: str) -> ParsedRelay:
    payload_inverse = _payload_labels(text)
    payload_labels = {value: key for key, value in payload_inverse.items()}
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not lines:
        raise ValueError("empty relay description")
    format_match = re.match(r"format:\s*(\S+)", lines[0])
    if not format_match:
        raise ValueError("format declaration missing")
    format_name = format_match.group(1)
    if format_name == "flat-relay-v1":
        rules_start = lines.index("rules:") + 1
        raw_rules = lines[rules_start:]
        parsed_rules: list[RelayRule] = []
        for line in raw_rules:
            match = _FLAT_RULE_RE.match(line)
            if not match:
                raise ValueError(f"invalid flat rule: {line!r}")
            source, target, expression = match.groups()
            operation, constant = _op_from_expr(expression, target, payload_inverse)
            parsed_rules.append(RelayRule(source, target, operation, constant))
        template_match = re.search(r"^templates:\s*(.+)$", text, re.M)
        if not template_match:
            raise ValueError("templates declaration missing")
        templates = tuple(item.strip() for item in template_match.group(1).split(","))
        system = RelaySystem(templates, (0, 1), tuple(parsed_rules), system_id=_system_id(text))
        transitions: dict[str, ConcreteTransition] = {
            rule.source: (rule.target, rule.payload_op, rule.constant)
            for rule in parsed_rules
        }
        return ParsedRelay(system, payload_labels, "flat", transitions)

    if format_name == "reflective-relay-v1":
        parsed_rules: list[RelayRule] = []
        current: str | None = None
        for line in lines:
            if line.startswith(("format:", "system:", "payloads:")):
                continue
            template_match = _REF_TEMPLATE_RE.match(line)
            if template_match:
                current = template_match.group(1)
                continue
            emit_match = _REF_EMIT_RE.match(line)
            if emit_match and current is not None:
                target, expression = emit_match.groups()
                operation, constant = _op_from_expr(expression, target, payload_inverse)
                parsed_rules.append(RelayRule(current, target, operation, constant))
                continue
            raise ValueError(f"invalid reflective line: {line!r}")
        templates = tuple(rule.source for rule in parsed_rules)
        system = RelaySystem(templates, (0, 1), tuple(parsed_rules), system_id="parsed-reflective")
        transitions = {
            rule.source: (rule.target, rule.payload_op, rule.constant)
            for rule in parsed_rules
        }
        return ParsedRelay(system, payload_labels, "reflective", transitions)

    raise ValueError(f"unknown relay format: {format_name}")


def concrete_rollout(parsed: ParsedRelay, initial_text: str, horizon: int) -> State:
    state = parsed.state_from_rendered(initial_text)
    for _ in range(horizon):
        state = parsed.concrete_transition(state)
    return state
