"""Flat relay renderer."""
from __future__ import annotations

from .schema import RelaySystem, State, SurfaceMapping


def render_state(state: State, mapping: SurfaceMapping) -> str:
    return f"{mapping.templates[state[0]]}({mapping.payloads[state[1]]})"


def _payload_expression(system: RelaySystem, source: str, mapping: SurfaceMapping) -> str:
    rule = system.rule_for(source)
    if rule.payload_op == "identity":
        return "payload"
    if rule.payload_op == "flip":
        return "flip(payload)"
    if rule.payload_op == "constant":
        return mapping.payloads[rule.constant or 0]
    raise ValueError(rule.payload_op)


def render_flat(
    system: RelaySystem,
    mapping: SurfaceMapping,
    *,
    syntax_noise: str = "clean",
) -> str:
    lines = [
        "format: flat-relay-v1",
        f"system: {system.system_id}",
        "templates: " + ", ".join(mapping.templates[name] for name in system.templates),
        f"payloads: {mapping.payloads[0]}, {mapping.payloads[1]}",
        "rules:",
    ]
    for source in system.templates:
        rule = system.rule_for(source)
        target = mapping.templates[rule.target]
        expression = _payload_expression(system, source, mapping)
        lines.append(f"- {mapping.templates[source]}(payload) -> {target}({expression})")
    if syntax_noise == "noisy":
        lines.insert(0, "# Names are arbitrary; comments do not change semantics.")
        lines.append("# End of flat relay.")
    elif syntax_noise != "clean":
        raise ValueError(syntax_noise)
    return "\n".join(lines)
