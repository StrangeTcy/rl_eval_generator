#!/usr/bin/env python3
"""Build a complete, manifest-driven inventory of generated environments.

This tool is deliberately inference-free.  It audits the declarative registry,
records every config and difficulty axis, and can optionally expand a matrix of
explicit difficulty/seed cases.  It never contacts a model provider and never
runs generated code unless ``--preflight`` is requested.

Examples:
    python tools/suite_inventory.py --out suite_manifest.json
    python tools/suite_inventory.py --out suite_all.json --matrix all --seeds 0,1
    python tools/suite_inventory.py --out suite_preflight.json --matrix all --preflight
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised in minimal installs
        raise RuntimeError("PyYAML is required to inspect config.yaml files") from exc
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: top-level YAML value must be a mapping")
    return loaded


def _load_registry(root: Path) -> dict[str, str]:
    registry_path = root / "envs" / "registry.yaml"
    if not registry_path.is_file():
        return {}
    data = _load_yaml(registry_path)
    environments = data.get("environments", {})
    if not isinstance(environments, dict):
        raise ValueError(f"{registry_path}: environments must be a mapping")
    result: dict[str, str] = {}
    for name, path in environments.items():
        if not isinstance(name, str) or not isinstance(path, str):
            raise ValueError(f"{registry_path}: environment names and paths must be strings")
        result[name] = path
    return result


def _track_for_path(path: Path) -> str:
    parts = set(path.parts)
    if "trajectory_semantics" in parts:
        return "trajectory_solver_synthesis"
    if "recurrent_depth" in parts:
        return "recurrent_depth_behavioral"
    if "cat_theo" in parts:
        return "category_theoretic_compositional"
    if "weird_machine" in parts:
        return "weird_machine"
    return "ml_debugging"


def _validate_axes(config: dict[str, Any], path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[str] = []
    axes = config.get("axes")
    if not isinstance(axes, list) or not axes:
        return [], [f"{path}: axes must be a non-empty list"]
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, axis in enumerate(axes):
        if not isinstance(axis, dict):
            issues.append(f"{path}: axes[{index}] is not a mapping")
            continue
        axis_id = axis.get("id")
        levels = axis.get("levels")
        if not isinstance(axis_id, str) or not axis_id:
            issues.append(f"{path}: axes[{index}] has no string id")
            continue
        if axis_id in seen_ids:
            issues.append(f"{path}: duplicate axis id {axis_id!r}")
        seen_ids.add(axis_id)
        if not isinstance(levels, dict) or not levels:
            issues.append(f"{path}: axis {axis_id!r} has no levels")
            continue
        level_names = [name for name in levels if isinstance(name, str) and name]
        if len(level_names) != len(levels):
            issues.append(f"{path}: axis {axis_id!r} has non-string or empty level names")
        normalized.append(
            {
                "id": axis_id,
                "description": str(axis.get("description", "")),
                "levels": sorted(level_names),
            }
        )
    return normalized, issues


def _difficulty_vectors(
    axes: list[dict[str, Any]],
    matrix: str,
    selected_levels: list[str] | None,
) -> list[dict[str, str]]:
    if not axes:
        return []
    if matrix == "all":
        choices = [axis["levels"] for axis in axes]
    elif matrix == "representative":
        choices = []
        for axis in axes:
            levels = axis["levels"]
            preferred = [level for level in selected_levels or [] if level in levels]
            choices.append(preferred[:1] or [levels[0]])
    else:  # pragma: no cover - argparse constrains this
        raise ValueError(f"unknown matrix {matrix!r}")
    return [
        {axis["id"]: level for axis, level in zip(axes, combination, strict=True)}
        for combination in itertools.product(*choices)
    ]


def _case_id(environment: str, difficulty: dict[str, str], seed: int) -> str:
    encoded = ",".join(f"{key}={difficulty[key]}" for key in difficulty)
    safe = "".join(char if char.isalnum() or char in "._=-" else "_" for char in encoded)
    return f"{environment}__{safe}__seed-{seed}"


def _registry_audit(
    root: Path,
    registry: dict[str, str],
    config_paths: list[Path],
) -> dict[str, Any]:
    relative_configs = {path.relative_to(root).as_posix(): path for path in config_paths}
    registry_paths: dict[str, list[str]] = {}
    for name, configured_path in registry.items():
        normalized = Path(configured_path).as_posix()
        registry_paths.setdefault(normalized, []).append(name)
    missing_paths = sorted(
        name for name, path in registry.items() if not (root / path).is_file()
    )
    unregistered_paths = sorted(set(relative_configs) - set(registry_paths))
    duplicate_paths = {
        path: names for path, names in registry_paths.items() if len(names) > 1
    }
    duplicate_names = len(registry) != len(set(registry))
    return {
        "registry_path": "envs/registry.yaml",
        "registry_entry_count": len(registry),
        "config_file_count": len(config_paths),
        "missing_registry_paths": missing_paths,
        "unregistered_config_paths": unregistered_paths,
        "duplicate_registry_paths": duplicate_paths,
        "duplicate_registry_names": duplicate_names,
        "clean": not (missing_paths or unregistered_paths or duplicate_paths or duplicate_names),
    }


def _preflight_case(case: dict[str, Any], root: Path) -> dict[str, Any]:
    """Generate and compile one case without starting Docker or a provider."""

    temp_dir = Path(tempfile.mkdtemp(prefix="suite-preflight-", dir=root))
    output_name = temp_dir.name + "-generated"
    output_dir = root / output_name
    difficulty = ",".join(case["difficulty_levels"].values())
    command = [
        sys.executable,
        "generate_env.py",
        "--env",
        case["environment"],
        "--name",
        output_name,
        "--difficulty",
        difficulty,
        "--seed",
        str(case["seed"]),
    ]
    try:
        generated = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if generated.returncode != 0:
            return {
                "status": "generation_error",
                "error": (generated.stdout + generated.stderr)[-4000:],
            }
        py_files = [str(path) for path in output_dir.rglob("*.py")]
        compiled = subprocess.run(
            [sys.executable, "-m", "py_compile", *py_files],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if compiled.returncode != 0:
            return {
                "status": "compile_error",
                "error": (compiled.stdout + compiled.stderr)[-4000:],
            }
        return {"status": "ready", "generated_file_count": sum(1 for _ in output_dir.rglob("*"))}
    except subprocess.TimeoutExpired:
        return {"status": "preflight_timeout", "error": "generation or compilation timed out"}
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(temp_dir, ignore_errors=True)


def build_manifest(
    *,
    root: Path = ROOT,
    matrix: str = "representative",
    seeds: list[int] | None = None,
    selected_levels: list[str] | None = None,
    preflight: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    registry = _load_registry(root)
    config_paths = sorted((root / "envs").rglob("config.yaml"))
    audit = _registry_audit(root, registry, config_paths)
    environments: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    seeds = list(seeds or [0])
    for config_path in config_paths:
        relative = config_path.relative_to(root).as_posix()
        names = [name for name, path in registry.items() if Path(path).as_posix() == relative]
        config = _load_yaml(config_path)
        axes, axis_issues = _validate_axes(config, config_path)
        if not names:
            name = config_path.parent.name
            names = [name]
        vectors = _difficulty_vectors(axes, matrix, selected_levels)
        environment = {
            "environment": names[0],
            "registry_names": sorted(names),
            "config_path": relative,
            "config_sha256": _sha256(config_path),
            "track": _track_for_path(config_path),
            "axes": axes,
            "axis_count": len(axes),
            "difficulty_vector_count": len(vectors),
            "issues": axis_issues,
        }
        environments.append(environment)
        for name in names[:1]:
            for difficulty in vectors:
                for seed in seeds:
                    case = {
                        "case_id": _case_id(name, difficulty, seed),
                        "environment": name,
                        "config_path": relative,
                        "config_sha256": environment["config_sha256"],
                        "track": environment["track"],
                        "runner": "arena_episode",
                        "difficulty_levels": difficulty,
                        "difficulty": ",".join(difficulty[axis["id"]] for axis in axes),
                        "seed": seed,
                        "status": "planned",
                    }
                    if preflight:
                        case.update(_preflight_case(case, root))
                    cases.append(case)
    issues = [
        *audit["missing_registry_paths"],
        *audit["unregistered_config_paths"],
        *[f"{path}: duplicate registry names {names}" for path, names in audit["duplicate_registry_paths"].items()],
        *[f"{env['environment']}: {issue}" for env in environments for issue in env["issues"]],
    ]
    commit = _git_value("rev-parse", "HEAD")
    dirty = _git_value("status", "--porcelain") or ""
    return {
        "schema_version": 1,
        "manifest_type": "rl_eval_generator_suite",
        "created_at": _utc_now(),
        "repository": {
            "commit": commit,
            "dirty": bool(dirty),
            "root": str(root),
        },
        "selection": {
            "matrix": matrix,
            "seeds": seeds,
            "selected_levels": selected_levels or [],
        },
        "registry_audit": audit,
        "environment_count": len(environments),
        "case_count": len(cases),
        "environments": environments,
        "cases": cases,
        "issues": issues,
        "ready_for_scheduler": not issues and all(
            case.get("status") in {"planned", "ready"} for case in cases
        ),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=Path("suite_manifest.json"))
    parser.add_argument(
        "--matrix",
        choices=("representative", "all"),
        default="representative",
        help="representative selects the first level per axis; all expands the Cartesian product",
    )
    parser.add_argument("--seeds", default="0", help="comma-separated integer seeds")
    parser.add_argument("--levels", default="easy,medium,hard", help="preferred levels for representative mode")
    parser.add_argument("--preflight", action="store_true", help="generate and compile each case")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        seeds = [int(value.strip()) for value in args.seeds.split(",") if value.strip()]
        levels = [value.strip() for value in args.levels.split(",") if value.strip()]
        manifest = build_manifest(
            root=args.root,
            matrix=args.matrix,
            seeds=seeds,
            selected_levels=levels,
            preflight=args.preflight,
        )
        write_json(args.out, manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"suite inventory failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "manifest": str(args.out),
                "environment_count": manifest["environment_count"],
                "case_count": manifest["case_count"],
                "registry_clean": manifest["registry_audit"]["clean"],
                "ready_for_scheduler": manifest["ready_for_scheduler"],
                "issue_count": len(manifest["issues"]),
            },
            indent=2,
        )
    )
    return 0 if manifest["ready_for_scheduler"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
