#!/usr/bin/env python3
"""Host-side behavioural references for the recursive local-to-global family.

``tools/instance_oracle_gate.py`` refuses to authorise a paid episode unless a
*correct* patch passes the real judge and a *plausible but wrong* patch fails the
held-out check that is supposed to catch it, on the exact generated instance the
episode will run.  This module supplies those two patches for the recursive
environments.  It is deliberately not a second solver framework:

* the correct patch embeds the environment's own ``network.py`` oracle into the
  generated ``solver.py`` and dispatches to its reference entry point.  The gate
  must certify that the *judge* separates correct from wrong; re-deriving a
  second solver here would certify this file instead of the environment;
* the wrong patch is the environment's own naive baseline (``arm_*``), or, for
  ``recursive_gluing``, a greedy one-pass propagation that ignores cross-depth
  overlaps - the tempting local-only strategy the environment exists to refute.

Both patches are written only into a throwaway gate workspace by the host.  No
model sees them, and nothing here is part of the agent-facing tree.

Coverage is intentionally partial.  ``recursive_holonomy_gluing`` remains
excluded pending executed positive/negative gate certification of its revised
transport contract. Its current pass threshold is 1.0. The historical 0.85
threshold allowed decisive global failures to be hidden by other checks;
repairing that source-level defect does not itself certify the revised judge.
``tools/recursive_gluing_study.py`` records the outstanding certification.

Only ``recursive_compiler_bootstrap`` currently pins ``representation`` to
``revealed``: its legacy decoder reference still needs the hidden encodings.
Codes and coarse-graining now recover their presentations from public
calibration. The exact-instance gate must still certify each selected case.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
ENV_ROOT = Path("envs") / "cat_theo"

# environment -> the authoritative oracle shipped with the environment
NETWORK_FILES: dict[str, str] = {
    name: (ENV_ROOT / name / "files" / "network.py").as_posix()
    for name in (
        "recursive_gluing",
        "recursive_gluing_discovery",
        "recursive_maze_gluing",
        "recursive_distributed_gluing",
        "recursive_epistemic_gluing",
        "recursive_coarse_graining",
        "recursive_compiler_bootstrap",
        "recursive_error_correcting_codes",
    )
}

# environment -> entry point in that oracle that returns a correct certificate
REFERENCE_ENTRY: dict[str, str] = {
    "recursive_gluing": "reference_solve",
    "recursive_gluing_discovery": "reference_certificate",
    "recursive_maze_gluing": "reference_certificate",
    "recursive_distributed_gluing": "reference_certificate",
    "recursive_epistemic_gluing": "reference_certificate",
    "recursive_coarse_graining": "reference_certificate",
    "recursive_compiler_bootstrap": "reference_certificate",
    "recursive_error_correcting_codes": "reference_certificate",
}

# environment -> the environment's own naive baseline, used as the wrong patch
WRONG_ARM: dict[str, str] = {
    "recursive_gluing_discovery": "arm_copy_leaf_upward",
    "recursive_distributed_gluing": "arm_numbers_only",
    "recursive_epistemic_gluing": "arm_actual_facts",
    "recursive_coarse_graining": "arm_local_only",
    "recursive_compiler_bootstrap": "arm_local_only",
    "recursive_error_correcting_codes": "arm_local_only",
}

# The held-out check the wrong patch must fail.  Every one of these is generated
# independently of the configured difficulty vector (an obstructed cycle, an
# assembled-unsat sibling), so the gate asserts the same distinction at every
# selected vector instead of depending on the row being hard enough.
NEGATIVE_CHECK: dict[str, str] = {
    "recursive_gluing": "obstructed_cycle",
    "recursive_gluing_discovery": "assembled_unsat",
    "recursive_maze_gluing": "assembled_unsat",
    "recursive_distributed_gluing": "assembled_unsat",
    "recursive_epistemic_gluing": "assembled_unsat",
    "recursive_coarse_graining": "assembled_unsat",
    "recursive_compiler_bootstrap": "assembled_unsat",
    "recursive_error_correcting_codes": "assembled_unsat",
}

# The maze flat-search negative control predates the strict 1.0 threshold.
# Under the historical 0.85 threshold, dropping orientation alone could still
# pass shallow cases. This retained control searches only the root tile,
# ignoring both orientation and nested shafts; the gate checks its named
# assembled-unsat failure on the current instance.
_MAZE_WRONG_SOURCE = '''
class {class_name}:
    """Tempting shortcut: search the root tile as if the maze were flat."""

    def solve(self, maze):
        tile = maze["tiles"][maze["root"]]
        start, goal = tile["entrance"], tile["exit"]
        adjacency = {}
        for edge in tile["edges"]:
            adjacency.setdefault(edge["from"], []).append(edge["to"])
        seen = {start}
        queue = [(start, [])]
        while queue:
            room, path = queue.pop(0)
            if room == goal:
                return {
                    "status": "sat",
                    "steps": [{"op": "move", "to": step} for step in path],
                }
            for nxt in adjacency.get(room, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, path + [nxt]))
        return {"status": "unsat"}
'''

# recursive_gluing ships no naive arm: its shipped stub ignores every overlap
# that crosses a nesting depth.  This is the same trap written as a solver that
# at least attempts propagation, so the gate is not merely catching a stub.
_CONTROL_WRONG_SOURCE = '''
class {class_name}:
    """Greedy one-pass propagation that ignores cross-depth overlaps."""

    def solve(self, instance):
        regions = instance["regions"]
        overlaps = instance["overlaps"]
        assignment = {rid: list(regions[rid]["domain"])[0] for rid in sorted(regions)}
        changed = True
        guard = 0
        while changed and guard < 50:
            changed = False
            guard += 1
            for overlap in overlaps:
                left, right = overlap["left"], overlap["right"]
                pairs = [(str(a), str(b)) for a, b in overlap["pairs"]]
                if left.count("/") != right.count("/"):
                    # Deferred "combination step": the locally convenient answer.
                    continue
                current = (assignment[left], assignment[right])
                if current in pairs:
                    continue
                forward = [b for a, b in pairs if a == current[0]]
                backward = [a for a, b in pairs if b == current[1]]
                if forward:
                    assignment[right] = forward[0]
                    changed = True
                elif backward:
                    assignment[left] = backward[0]
                    changed = True
                else:
                    return {"status": "unsat"}
        return {"status": "sat", "assignment": assignment}
'''


# The generated ``solver.py`` is compiled by the environment's own source
# validator, whose allowlist is deliberately narrow.  The embedded oracle is
# therefore stripped of imports the agent-facing solver may not use; if the
# reference path needs one of them the gate fails closed instead of shipping a
# solver the environment would reject.
_ALLOWED_IMPORTS = frozenset({
    "torch", "torchvision", "math", "random", "collections", "functools",
    "itertools", "typing", "dataclasses", "enum", "abc", "copy", "numbers",
    "operator", "string", "textwrap", "PIL", "numpy", "warnings", "contextlib",
    "time",
})
_BANNED_NAMES = frozenset({
    "exec", "eval", "compile", "__import__", "open", "globals", "locals", "vars",
    "__builtins__", "__loader__", "__spec__", "breakpoint",
})


# Explicit wrong patches for environments whose shipped naive arm still clears
# the environment's own pass threshold on some vectors, so the gate correctly
# refuses it as a negative control.  Each one is the same tempting shortcut
# taken as far as it will go, written against the environment's own oracle
# helpers (the source below is appended to the embedded network.py).
WRONG_SOURCE: dict[str, str] = {
    "recursive_gluing": _CONTROL_WRONG_SOURCE,
    "recursive_maze_gluing": _MAZE_WRONG_SOURCE,
}


class ReferenceUnavailable(RuntimeError):
    """Raised when an environment has no configured behavioural reference."""


def sanitize_solver_source(source: str, environment: str) -> str:
    """Drop imports the generated solver validator would reject.

    Losing an import is safe only when the reference path does not use it; the
    exact-instance gate is what proves that, and a runtime failure surfaces as a
    gate failure rather than as a scored result.
    """

    tree = ast.parse(source)
    disallowed: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] not in _ALLOWED_IMPORTS for alias in node.names):
                disallowed.append((node.lineno, node.end_lineno or node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] not in _ALLOWED_IMPORTS:
                disallowed.append((node.lineno, node.end_lineno or node.lineno))
    lines = source.splitlines()
    for start, end in sorted(disallowed, reverse=True):
        del lines[start - 1 : end]
    sanitized = "\n".join(lines)
    banned = sorted(
        {
            node.id
            for node in ast.walk(ast.parse(sanitized))
            if isinstance(node, ast.Name) and node.id in _BANNED_NAMES
        }
    )
    if banned:
        raise ReferenceUnavailable(
            f"{environment}: the oracle source uses names the generated solver validator "
            f"bans ({banned}); the reference cannot be embedded without changing the task"
        )
    return sanitized


def reference_environments() -> tuple[str, ...]:
    """Environments whose correct/wrong pair is configured here."""

    return tuple(sorted(NETWORK_FILES))


def _class_name(workspace: Path) -> str:
    tree = ast.parse((workspace / "solver.py").read_text(encoding="utf-8"))
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        raise ValueError(f"solver.py: expected one class, found {classes}")
    return classes[0]


def solver_source(environment: str, *, wrong: bool) -> str:
    """Build the reference (or deliberately wrong) ``solver.py`` body."""

    if environment not in NETWORK_FILES:
        raise ReferenceUnavailable(
            f"no behavioural reference configured for {environment!r}; "
            f"configured: {', '.join(reference_environments())}"
        )
    network_path = ROOT / NETWORK_FILES[environment]
    if not network_path.is_file():
        raise FileNotFoundError(f"missing oracle source: {network_path}")
    network_source = sanitize_solver_source(
        network_path.read_text(encoding="utf-8"), environment
    )
    if wrong:
        if environment in WRONG_SOURCE:
            # Explicit wrong patches may use the oracle's own helpers, so they are
            # appended to the embedded source rather than replacing it.
            return network_source + WRONG_SOURCE[environment]
        entry = WRONG_ARM[environment]
    else:
        entry = REFERENCE_ENTRY[environment]
    if f"def {entry}(" not in network_source:
        raise ReferenceUnavailable(
            f"{NETWORK_FILES[environment]} has no {entry!r}; the environment changed "
            "and the gate reference must be re-checked"
        )
    wrapper = (
        "\n\nclass {class_name}:\n"
        '    """Gate-only reference; written by the host into a throwaway workspace."""\n\n'
        "    def solve(self, instance):\n"
        f"        return {entry}(instance)\n"
    )
    return network_source + wrapper


def reference_patch(environment: str) -> Callable[..., Any]:
    """Return ``apply(workspace, *, wrong)`` for ``instance_oracle_gate``."""

    if environment not in NETWORK_FILES:
        raise ReferenceUnavailable(f"no behavioural reference configured for {environment!r}")

    def apply(workspace: Path, *, wrong: bool) -> None:
        workspace = Path(workspace)
        class_name = _class_name(workspace)
        source = solver_source(environment, wrong=wrong).replace("{class_name}", class_name)
        (workspace / "solver.py").write_text(source, encoding="utf-8")

    return apply


def references() -> dict[str, tuple[Callable[..., Any], str]]:
    """``{environment: (apply, negative_check)}`` for the exact-instance gate."""

    return {
        environment: (reference_patch(environment), NEGATIVE_CHECK[environment])
        for environment in reference_environments()
    }


__all__ = [
    "NEGATIVE_CHECK",
    "NETWORK_FILES",
    "REFERENCE_ENTRY",
    "ReferenceUnavailable",
    "WRONG_ARM",
    "WRONG_SOURCE",
    "reference_environments",
    "reference_patch",
    "references",
    "sanitize_solver_source",
    "solver_source",
]
