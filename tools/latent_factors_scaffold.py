#!/usr/bin/env python3
"""Emit starter ``latent_factors:`` blocks for environment configs (item 4, PR-C).

Decision item 4 requires every config to declare its latent factors, and accepted
the consequence: ~33 configs of authoring before the layer is registry-complete.
This tool makes that a checklist instead of a silent quality downgrade.  It maps
every placeholder an environment instantiates onto the factor vocabulary with
fixed, mechanical rules, and stamps the result ``declared_by: scaffold_unreviewed``
so a mechanical declaration can never be cited as a causal claim.  Reviewing a
block means editing it and moving the stamp to ``human``.

The rules, in precedence order:

1. placeholder patterns, applied regardless of axis tags: a name containing
   ``TEST`` is a proxy signal (what a proxy-chasing agent can read instead of the
   invariant); a name containing ``COMMENT``/``HINT``/``CLUE``/``NOTE``/
   ``DOCSTRING``/``HERRING`` is a planted cue - observable_state even inside a
   task-class axis, which is what keeps moco's ``QUEUE_HINT`` (a queue_math value)
   out of task identity and a ``retrieval_cue`` twin paired with its baseline.
2. the axis ``class:`` tag where one exists (item 3): task -> task_state,
   observation/presentation -> observable_state, evaluator -> evaluator_state.
3. untagged axes only: ids ``naming``/``surface_deceptiveness``/``representation``
   are presentation in registry idiom -> observable_state.
4. untagged axes only: naming-shaped placeholders (``MODEL_CLASS``, ``*_FILE``,
   ``*_MODULE``, ``*_VAR``, ``*_FN``, ``*_ATTR``, ``*_CLASS``) -> observable_state.
5. default: task_state.  Conservative on purpose - an over-broad identity splits
   pairs that a later review merges, while an over-narrow one silently merges
   tasks that are different, which is the worse error.

Renderer environments get ``source: instance_spec`` on task_state: their identity
is the judge-baked ground truth.  The scaffold emits an empty ``identity_keys``
projection, which means "the whole baked spec" - the one projection in the
registry (``epistemic_games``) is hand-authored, because choosing which keys of a
ground truth carry task identity is exactly the claim a scaffold may not make.

Examples:
    python tools/latent_factors_scaffold.py --all            # print every block
    python tools/latent_factors_scaffold.py --env moco       # print one block
    python tools/latent_factors_scaffold.py --all --write    # append missing blocks
    python tools/latent_factors_scaffold.py --check          # registry completeness
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import generate_env as ge  # noqa: E402
from shared import latent_spec as ls  # noqa: E402

_CUE_PATTERN = re.compile(r"COMMENT|HINT|CLUE|NOTE|DOCSTRING|HERRING")
_PRESENTATION_AXIS_IDS = {"naming", "surface_deceptiveness", "representation"}
_NAMING_SHAPE = re.compile(r"_(CLASS|FILE|MODULE|VAR|FN|ATTR)$")
_NAMING_EXACT = {"MODEL_CLASS", "MODEL_FILE", "MODEL_MODULE"}


def classify_placeholder(axis_id: str, axis_class: str | None, name: str) -> tuple[str, str]:
    """(factor, rule) for one placeholder, by the precedence documented above."""
    if "TEST" in name:
        return "proxy_signal", "pattern:TEST"
    if _CUE_PATTERN.search(name):
        return "observable_state", "pattern:cue-text"
    if axis_class == "task":
        return "task_state", "axis_class:task"
    if axis_class in ("observation", "presentation"):
        return "observable_state", f"axis_class:{axis_class}"
    if axis_class == "evaluator":
        return "evaluator_state", "axis_class:evaluator"
    if axis_id in _PRESENTATION_AXIS_IDS:
        return "observable_state", f"axis_id:{axis_id}"
    if name in _NAMING_EXACT or _NAMING_SHAPE.search(name):
        return "observable_state", "pattern:naming-shape"
    return "task_state", "default:task_state"


def build_block(config: dict[str, Any]) -> dict[str, Any]:
    """The scaffold declaration for one loaded config."""
    assignments: dict[str, list[str]] = {
        "task_state": [], "observable_state": [], "proxy_signal": [], "evaluator_state": [],
    }
    rules: dict[str, list[str]] = {key: [] for key in assignments}
    for axis in config.get("axes") or []:
        axis_id = str(axis.get("id") or "")
        axis_class = axis.get("class")
        names: set[str] = set()
        for level in (axis.get("levels") or {}).values():
            for key in (level or {}):
                names.add(ge.gm.strip_placeholders(str(key)))
        for name in sorted(names):
            factor, rule = classify_placeholder(axis_id, axis_class, name)
            assignments[factor].append(name)
            rules[factor].append(f"{name} <- {rule}")

    has_renderer = bool(config.get("renderer"))
    factors: dict[str, Any] = {}
    if has_renderer:
        task: dict[str, Any] = {"source": "instance_spec", "identity_keys": []}
        if assignments["task_state"]:
            task["placeholders"] = assignments["task_state"]
        factors["task_state"] = task
    elif assignments["task_state"]:
        factors["task_state"] = {"placeholders": assignments["task_state"]}
    else:
        factors["task_state"] = {
            ls.UNAVAILABLE: "scaffold rules mapped no placeholder to task_state; "
            "identity rests on evaluator_state until a review declares it",
        }
    factors["causal_mechanism"] = {
        ls.UNAVAILABLE: "fixed hand-authored template code; a scaffold cannot derive "
        "a generative mechanism, and recording one it did not derive would be a "
        "causal claim nobody made (item 4 honesty constraint)",
    }
    if assignments["observable_state"]:
        factors["observable_state"] = {"placeholders": assignments["observable_state"]}
    else:
        factors["observable_state"] = {
            ls.UNAVAILABLE: "scaffold rules mapped no placeholder to observable_state",
        }
    if assignments["proxy_signal"]:
        factors["proxy_signal"] = {"placeholders": assignments["proxy_signal"]}
    else:
        factors["proxy_signal"] = {
            ls.UNAVAILABLE: "scaffold rules mapped no placeholder to proxy_signal",
        }
    evaluator: dict[str, Any] = {"scoring": True, "constants": True, "judge_files": True}
    if assignments["evaluator_state"]:
        evaluator["placeholders"] = assignments["evaluator_state"]
    factors["evaluator_state"] = evaluator
    factors["agent_belief"] = {
        ls.UNAVAILABLE: "not a property of the instance at generation time; item 8 "
        "approximates it at run time and says not_measurable where it cannot",
    }
    return {
        "schema_version": ls.SPEC_SCHEMA_VERSION,
        "declared_by": "scaffold_unreviewed",
        "factors": factors,
        "_rules": rules,
    }


def render_block(block: dict[str, Any], env_name: str) -> str:
    """Deterministic YAML text for the block, with the applied rules as comments."""
    rules = block.get("_rules") or {}
    lines = [
        "",
        "# Latent factors (decision item 4, PR-C): what this environment's task identity",
        "# is declared to be.  Scaffold-generated by tools/latent_factors_scaffold.py from",
        "# axis classes, axis ids and placeholder patterns; `declared_by:",
        "# scaffold_unreviewed` means no one has certified these as causal claims - move",
        "# the stamp to `human` when the mapping below has been reviewed.",
        "latent_factors:",
        f"  schema_version: {block['schema_version']}",
        f"  declared_by: {block['declared_by']}",
        "  factors:",
    ]

    def emit_factor(name: str) -> None:
        decl = block["factors"][name]
        lines.append(f"    {name}:")
        for rule_line in rules.get(name) or []:
            lines.append(f"      # {rule_line}")
        if ls.UNAVAILABLE in decl:
            reason = decl[ls.UNAVAILABLE]
            dumped = yaml.safe_dump({ls.UNAVAILABLE: reason}, default_flow_style=False, width=88)
            for rendered in dumped.splitlines():
                lines.append(f"      {rendered}")
            return
        if decl.get("source"):
            lines.append(f"      source: {decl['source']}")
        if "identity_keys" in decl:
            keys = decl["identity_keys"]
            if keys:
                lines.append("      identity_keys:")
                lines.extend(f"        - {key}" for key in keys)
            else:
                lines.append(
                    "      identity_keys: []   # whole baked spec; author a projection on review"
                )
        for key in ("scoring", "constants", "judge_files"):
            if key in decl:
                lines.append(f"      {key}: {'true' if decl[key] else 'false'}")
        if decl.get("placeholders"):
            lines.append(f"      placeholders: [{', '.join(decl['placeholders'])}]")

    for name in ls.FACTORS:
        emit_factor(name)
    lines.append("")
    return "\n".join(lines)


def registry_configs() -> list[tuple[str, Path]]:
    registry = ge._load_registry()
    seen: dict[str, str] = {}
    for name, path in registry.items():
        seen.setdefault(str(path), name)
    return sorted((name, ROOT / path) for path, name in seen.items())


def write_block(config_path: Path, text: str) -> bool:
    current = config_path.read_text(encoding="utf-8")
    if re.search(r"(?m)^latent_factors:", current):
        return False
    if current and not current.endswith("\n"):
        current += "\n"
    config_path.write_text(current + text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", help="registry name of one environment")
    parser.add_argument("--all", action="store_true", help="every registry environment")
    parser.add_argument("--write", action="store_true", help="append missing blocks to the configs")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero unless every registry config declares a valid block",
    )
    args = parser.parse_args(argv)
    cwd = Path.cwd()
    os.chdir(ROOT)
    try:
        targets = registry_configs()
        if args.env:
            targets = [(name, path) for name, path in targets if name == args.env]
            if not targets:
                print(f"no registry environment named {args.env!r}", file=sys.stderr)
                return 2
        if not (args.all or args.env or args.check):
            parser.error("one of --env, --all or --check is required")

        if args.check:
            failures = 0
            for name, path in targets:
                config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                errors = ls.validate_latent_factors(config, name)
                if errors:
                    failures += 1
                    for error in errors:
                        print(f"latent_factors: {error}", file=sys.stderr)
            print(
                f"latent registry: {len(targets) - failures}/{len(targets)} configs declare "
                "a valid latent_factors block"
            )
            return 1 if failures else 0

        written = 0
        for name, path in targets:
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if args.write and re.search(r"(?m)^latent_factors:", path.read_text(encoding="utf-8")):
                print(f"{name}: latent_factors already declared, left untouched")
                continue
            block = build_block(config)
            text = render_block(block, name)
            if args.write:
                write_block(path, text)
                written += 1
                print(f"{name}: block appended to {path.relative_to(ROOT)}")
            else:
                print(f"# ---- {name} ({path.relative_to(ROOT)}) ----{text}")
        if args.write:
            # Validate what now stands in every touched config.
            bad = 0
            for name, path in targets:
                config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                errors = ls.validate_latent_factors(config, name)
                for error in errors:
                    bad += 1
                    print(f"latent_factors: {error}", file=sys.stderr)
            if bad:
                return 1
            print(f"scaffold: wrote {written} block(s); every registry block validates")
        return 0
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    sys.exit(main())
