#!/usr/bin/env python3
"""Expand one environment into a causal-experiment family and verify the expansion.

A family is a base instance plus one member per declared intervention, all sharing
the same seed and difficulty vector, so that a difference between members is
attributable to the declared intervention rather than to a different task instance.
Generation is followed by ``twin_check``: the expectation is verified against the
bytes before any model is contacted, which is what stops "the agent was invariant"
from meaning "the intervention did nothing".

Examples:
    python tools/family.py --env moco --difficulty easy,easy,easy,easy,easy,easy \\
        --seeds 3 --interventions terminology,retrieval_cue --out families/moco
    python tools/family.py --spec specs/invariant-vs-proxy.yaml --out families/ivp --check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import generate_env as ge  # noqa: E402
import yaml  # noqa: E402
from shared import experiment_spec as es  # noqa: E402
from shared import generation_manifest as gm  # noqa: E402
from tools import twin_check  # noqa: E402


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return cleaned or "base"


def implemented_by(env_name: str) -> list[str]:
    """Intervention ids one environment actually realizes."""
    try:
        config = ge.load_config(env_name)
    except (SystemExit, ValueError):
        return []
    return sorted((config.get("interventions") or {}).keys())


def registry_implementations() -> dict[str, list[str]]:
    registry = ge._load_registry()
    return {name: implemented_by(name) for name in sorted(set(registry))}


def registry_names() -> list[str]:
    return sorted(set(ge._load_registry()))


def plan_members(
    env_name: str,
    difficulty: str,
    seeds: list[int],
    intervention_ids: list[str],
) -> list[dict[str, Any]]:
    """Base member plus one single-intervention member per id, per seed.

    One intervention per member, deliberately: a member that applies three overlays
    at once cannot attribute a score change to any of them, which is the whole
    content of the exercise.  Combinations belong in a spec as their own members.
    """
    config = ge.load_config(env_name)
    levels = ge.parse_difficulty(difficulty, config["axes"])
    plan: list[dict[str, Any]] = []
    for seed in seeds:
        plan.append(
            {
                "role": "baseline",
                "environment": env_name,
                "difficulty": dict(levels),
                "difficulty_string": difficulty,
                "seed": int(seed),
                "interventions": [],
            }
        )
        for iid in intervention_ids:
            plan.append(
                {
                    "role": "member",
                    "environment": env_name,
                    "difficulty": dict(levels),
                    "difficulty_string": difficulty,
                    "seed": int(seed),
                    "interventions": [iid],
                }
            )
    return plan


def member_name(item: dict[str, Any]) -> str:
    difficulty = "_".join(f"{key}={value}" for key, value in sorted(item["difficulty"].items()))
    interventions = "+".join(item["interventions"]) or "baseline"
    return _slug(f"{item['environment']}__{difficulty}__{interventions}__seed-{item['seed']}")


def generate_family(
    plan: list[dict[str, Any]],
    out_dir: Path,
    *,
    check: bool = True,
    strict: bool = False,
) -> dict[str, Any]:
    """Generate every planned member, then verify each against its baseline."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd()
    # generate_env resolves envs/ and shared/ relative to the repo root.
    import os

    os.chdir(ROOT)
    try:
        members: list[dict[str, Any]] = []
        baselines: dict[tuple[str, int], dict[str, Any]] = {}
        for item in plan:
            name = member_name(item)
            directory = out_dir / name
            levels = dict(item["difficulty"])
            interventions = list(item["interventions"])
            parent_id = None
            if interventions:
                baseline_record = baselines.get((item["environment"], int(item["seed"])))
                if baseline_record is not None:
                    parent_id = baseline_record.get("generation_id")
            manifest = ge.generate_env(
                item["environment"],
                str(directory),
                levels,
                seed=int(item["seed"]),
                interventions=interventions,
                parent_generation_id=parent_id,
            )
            record = {
                "name": name,
                "path": str(directory.relative_to(out_dir)),
                "role": item["role"],
                "generation_id": manifest["generation_id"],
                "parent_generation_id": manifest.get("parent_generation_id"),
                "pair_id": manifest["pair_id"],
                "pair_id_basis": manifest["pair_id_basis"],
                "equivalences": sorted(
                    {str(overlay["equivalence"]) for overlay in manifest["interventions"]}
                ),
                "expected_invariances": manifest["expected_invariances"],
                "expected_differences": manifest["expected_differences"],
                "config_sha256": manifest["config_sha256"],
                "tree_sha256": manifest["tree_sha256"],
                "spec_id": item.get("spec_id"),
            }
            if not interventions:
                baselines[(item["environment"], int(item["seed"]))] = record
            if check and interventions:
                baseline = baselines.get((item["environment"], int(item["seed"])))
                if baseline is None:
                    record["check"] = {
                        "status": "unverified",
                        "problems": ["no baseline member was generated for this seed"],
                    }
                else:
                    report = twin_check.compare(out_dir / baseline["name"], directory)
                    record["check"] = report
                    record["shares_pair_id_with_baseline"] = report["pair_id_base"] == report[
                        "pair_id_twin"
                    ]
            members.append(record)

        family = {
            "schema_version": gm.MANIFEST_SCHEMA_VERSION,
            "manifest_type": "rl_eval_generator_family",
            "generator_version": ge.generator_version(),
            "repository": {"commit": ge._git_commit()},
            "member_count": len(members),
            "members": members,
        }
        _summarize(family, strict=strict)
        target = out_dir / gm.FAMILY_MANIFEST_NAME
        target.write_text(json.dumps(family, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return family
    finally:
        os.chdir(cwd)


def _summarize(family: dict[str, Any], *, strict: bool) -> None:
    counts = {"pass": 0, "fail": 0, "unverified": 0, "unchecked": 0}
    failures: list[dict[str, Any]] = []
    for member in family["members"]:
        report = member.get("check")
        if report is None:
            counts["unchecked"] += 1
            continue
        status = str(report.get("status") or "unverified")
        counts[status if status in counts else "unverified"] += 1
        if status == "fail" or (strict and status == "unverified"):
            failures.append(
                {
                    "member": member["name"],
                    "status": status,
                    "problems": report.get("problems", []),
                    "notes": report.get("notes", []),
                }
            )
    family["verification"] = {
        "counts": counts,
        "failures": failures,
        "unverified_are_failures": strict,
        "reading": (
            "pass means the generated trees match the declared equivalence; it says "
            "nothing yet about any model. unverified means the declaration could not be "
            "checked mechanically and must not be reported as an invariance."
        ),
    }
    family["ok"] = not failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", default=None, help="environment name from envs/registry.yaml")
    parser.add_argument("--difficulty", default="", help="one level per axis, comma separated")
    parser.add_argument("--seeds", default="0", help="comma-separated seeds")
    parser.add_argument("--interventions", default="", help="comma-separated intervention ids")
    parser.add_argument("--out", type=Path, required=True, help="family output directory")
    parser.add_argument("--spec", type=Path, default=None, help="environment experiment spec")
    parser.add_argument("--list-interventions", action="store_true", help="what each env implements")
    parser.add_argument("--allow-advisory", action="store_true", help="downgrade spec errors to warnings")
    parser.add_argument("--strict", action="store_true", help="treat unverified checks as failures")
    parser.add_argument("--no-generate", action="store_true", help="validate/plan only")
    parser.add_argument("--json", type=Path, default=None, help="also write the family manifest here")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    taxonomy = ge.load_intervention_taxonomy()

    if args.list_interventions:
        for name, ids in registry_implementations().items():
            print(f"{name}: {', '.join(ids) if ids else '(none)'}")
        print(f"taxonomy: {', '.join(sorted(taxonomy))}")
        return 0

    plan: list[dict[str, Any]] = []
    warnings: list[str] = []

    if args.spec is not None:
        spec = yaml.safe_load(args.spec.read_text(encoding="utf-8")) or {}
        implemented = registry_implementations()
        errors, spec_warnings = es.validate_spec(
            spec,
            taxonomy=taxonomy,
            implemented=implemented,
            known_environments=registry_names(),
        )
        warnings.extend(spec_warnings)
        if errors:
            for error in errors:
                print(f"spec error: {error}", file=sys.stderr)
            if not args.allow_advisory:
                print(
                    "refusing to generate: these errors are the experiment being "
                    "incoherent, not cosmetic (use --allow-advisory to inspect anyway)",
                    file=sys.stderr,
                )
                return 2
            warnings.extend(f"spec error downgraded: {error}" for error in errors)
        for member in es.compile_members(spec):
            for seed in member["seeds"]:
                try:
                    levels = _levels_for(member["environment"], member["difficulty"])
                except (ValueError, SystemExit) as exc:
                    print(f"spec member {member['id']}: {exc}", file=sys.stderr)
                    return 2
                plan.append(
                    {
                        "role": "baseline" if not member["interventions"] else "member",
                        "environment": member["environment"],
                        "difficulty": levels,
                        "difficulty_string": member["difficulty"],
                        "seed": int(seed),
                        "interventions": list(member["interventions"]),
                        "spec_id": str(spec.get("id")),
                        "expect": member["expect"],
                        "measurements": member["measurements"],
                        "hypotheses": member["hypotheses"],
                    }
                )
    else:
        if not args.env or not args.difficulty:
            print("either --spec or (--env and --difficulty) is required", file=sys.stderr)
            return 2
        seeds = [int(seed) for seed in args.seeds.split(",") if seed.strip()]
        requested = ge.parse_intervention_ids(args.interventions)
        config = ge.load_config(args.env)
        supported = set(implemented_by(args.env))
        unknown = [iid for iid in requested if iid not in supported]
        if unknown:
            print(
                f"{args.env} does not implement: {', '.join(unknown)}. "
                f"Implemented here: {', '.join(sorted(supported)) or '(none)'}",
                file=sys.stderr,
            )
            return 2
        plan = plan_members(args.env, args.difficulty, seeds, requested)

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.no_generate:
        print(json.dumps({"plan": [member_name(item) for item in plan]}, indent=2))
        return 0

    try:
        family = generate_family(plan, args.out, check=True, strict=args.strict)
    except (ValueError, FileNotFoundError) as exc:
        print(f"family generation failed: {exc}", file=sys.stderr)
        return 2
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(family, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts = family["verification"]["counts"]
    print(
        f"\nfamily: {family['member_count']} members in {args.out} "
        f"(pass {counts['pass']}, fail {counts['fail']}, "
        f"unverified {counts['unverified']}, baseline {counts['unchecked']})"
    )
    for failure in family["verification"]["failures"]:
        print(f"  FAIL {failure['member']}")
        for problem in failure["problems"]:
            print(f"    - {problem}")
    return 0 if family["ok"] else 1


def _levels_for(env_name: str, difficulty_string: str) -> dict[str, str]:
    """Parse a spec's difficulty string against the environment's own axes."""
    config = ge.load_config(env_name)
    axes = config["axes"]
    levels = [part.strip().lower() for part in difficulty_string.split(",") if part.strip()]
    if len(levels) != len(axes):
        raise ValueError(
            f"spec member for {env_name!r}: difficulty has {len(levels)} levels but the "
            f"environment has {len(axes)} axes ({', '.join(axis['id'] for axis in axes)})"
        )
    return {axis["id"]: level for axis, level in zip(axes, levels)}


if __name__ == "__main__":
    sys.exit(main())
