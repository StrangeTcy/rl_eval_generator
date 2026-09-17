"""Restricted source-template relay renderer.

The representation is intentionally an operational DSL, not English prose.  The
judge parses emitted source with ``rendered_parser.py`` and never calls eval or
exec.
"""
from __future__ import annotations

from .schema import RelaySystem, State, SurfaceMapping


def render_state(state: State, mapping: SurfaceMapping) -> str:
    return f"{mapping.templates[state[0]]}({mapping.payloads[state[1]]})"


def render_reflective(
    system: RelaySystem,
    mapping: SurfaceMapping,
    *,
    syntax_noise: str = "clean",
) -> str:
    lines = [
        "format: reflective-relay-v1",
        f"payloads: {mapping.payloads[0]}, {mapping.payloads[1]}",
    ]
    for name in system.templates:
        rule = system.rule_for(name)
        source = mapping.templates[rule.target]
        if rule.payload_op == "identity":
            payload_expr = "payload"
        elif rule.payload_op == "flip":
            payload_expr = "flip(payload)"
        elif rule.payload_op == "constant":
            payload_expr = mapping.payloads[rule.constant or 0]
        else:
            raise ValueError(rule.payload_op)
        lines.extend(
            [
                "",
                f"template {mapping.templates[name]}(payload):",
                f'  emit_source("{source}({payload_expr})")',
            ]
        )
    if syntax_noise == "noisy":
        lines.insert(0, "# Quoted source is parsed as the next relay state.")
        lines.append("# End of reflective relay.")
    elif syntax_noise != "clean":
        raise ValueError(syntax_noise)
    return "\n".join(lines)
