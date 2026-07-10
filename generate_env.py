#!/usr/bin/env python3
"""
Generate complete evaluation environments from declarative configs.

Usage:
    python generate_env.py --env glyph --name glyph_hard --difficulty hard,hard,hard,hard,hard
    python generate_env.py --env batchnorm_ema --name bn_medium --difficulty medium,medium,medium,medium
    python generate_env.py --env moco --name moco_hard --difficulty hard,hard,hard,hard,hard
    python generate_env.py --env glyph --list-axes
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Environment Registry
# ---------------------------------------------------------------------------

_REGISTRY: Optional[Dict[str, str]] = None


def _load_registry() -> Dict[str, str]:
    """Load environment registry from envs/registry.yaml."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    registry_path = Path("envs") / "registry.yaml"
    if not registry_path.is_file():
        # Fallback: build registry by scanning for config.yaml files
        _REGISTRY = _build_registry_from_filesystem()
    else:
        with registry_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
            _REGISTRY = {}
            for env_name, config_path in data.get("environments", {}).items():
                _REGISTRY[env_name] = config_path
    return _REGISTRY


def _build_registry_from_filesystem() -> Dict[str, str]:
    """Build registry by scanning for config.yaml files under envs/."""
    registry: Dict[str, str] = {}
    envs_dir = Path("envs")
    if not envs_dir.is_dir():
        return registry
    for config_path in envs_dir.rglob("config.yaml"):
        # config_path is like: envs/glyph/config.yaml or envs/cat_theo/tensor_functor/config.yaml
        # We want the env name to be the directory name containing config.yaml
        config_dir = config_path.parent
        # Remove the envs/ prefix
        relative = config_dir.relative_to(envs_dir)
        env_name = str(relative).replace("\\", "/").replace("/", "_")
        # But also register with the actual directory structure
        registry[env_name] = str(config_path)
        # Also register with the nested path for backwards compatibility
        parts = list(relative.parts)
        if len(parts) > 0:
            registry[parts[-1]] = str(config_path)
    return registry


def resolve_env_path(env_name: str) -> Optional[Path]:
    """Resolve an environment name to its config.yaml path using the registry."""
    registry = _load_registry()
    if env_name in registry:
        return Path(registry[env_name])
    return None


def load_config(env_name: str) -> dict:
    """Load environment config, using registry-based lookup."""
    # Try registry first
    config_path = resolve_env_path(env_name)
    if config_path is not None and config_path.is_file():
        with config_path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    # Fallback to old hardcoded chain for backwards compatibility
    config_path = Path("envs") / env_name / "config.yaml"
    if not config_path.is_file():
        config_path = Path("envs") / "cat_theo" / env_name / "config.yaml"
    if not config_path.is_file():
        config_path = Path("envs") / "cat_theo" / "semiring" / env_name / "config.yaml"
    if not config_path.is_file():
        config_path = Path("envs") / "cat_theo" / "sheaf" / env_name / "config.yaml"
    if not config_path.is_file():
        config_path = Path("envs") / "weird_machine" / env_name / "config.yaml"
    if not config_path.is_file():
        print(f"ERROR: Config not found for '{env_name}'")
        sys.exit(1)
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_files_dir(env_name: str) -> Path:
    """Find the files directory for an environment using registry-based lookup."""
    # Try registry first
    config_path = resolve_env_path(env_name)
    if config_path is not None:
        # files dir is sibling to config.yaml
        files_dir = config_path.parent / "files"
        if files_dir.is_dir():
            return files_dir
    
    # Fallback to old hardcoded chain for backwards compatibility
    files_dir = Path("envs") / env_name / "files"
    if not files_dir.is_dir():
        files_dir = Path("envs") / "cat_theo" / env_name / "files"
    if not files_dir.is_dir():
        files_dir = Path("envs") / "cat_theo" / "semiring" / env_name / "files"
    if not files_dir.is_dir():
        files_dir = Path("envs") / "cat_theo" / "sheaf" / env_name / "files"
    if not files_dir.is_dir():
        files_dir = Path("envs") / "weird_machine" / env_name / "files"
    return files_dir


def validate_config(config: dict, files_dir: Path, env_name: str) -> None:
    errors: List[str] = []

    for key in ("axes", "layout"):
        if key not in config:
            errors.append(f"Missing required top-level key: '{key}'")

    axes = config.get("axes", [])
    if not isinstance(axes, list) or len(axes) == 0:
        errors.append("'axes' must be a non-empty list")
    else:
        for i, ax in enumerate(axes):
            if not isinstance(ax, dict):
                errors.append(f"axes[{i}]: must be a mapping")
                continue
            if "id" not in ax:
                errors.append(f"axes[{i}]: missing 'id'")
            if "levels" not in ax:
                errors.append(f"axes[{i}]: missing 'levels'")
                continue
            if not isinstance(ax["levels"], dict):
                errors.append(f"axes[{i}]: 'levels' must be a mapping")
                continue
            if len(ax["levels"]) == 0:
                errors.append(f"axes[{i}] '{ax.get('id', '?')}': 'levels' is empty")
            for level_name, mapping in ax["levels"].items():
                if mapping is not None and not isinstance(mapping, dict):
                    errors.append(
                        f"axes[{i}] '{ax.get('id', '?')}' level '{level_name}': "
                        "value must be a mapping or null"
                    )

    layout = config.get("layout", {})
    if not isinstance(layout, dict):
        errors.append("'layout' must be a mapping")
    else:
        static_files = set(config.get("static_files", []))
        for target, source in layout.items():
            source_str = str(source)
            if "%%" not in source_str:
                if source_str.startswith("shared/"):
                    src_path = Path(source_str)
                else:
                    src_path = files_dir / source_str

                if not src_path.is_file():
                    errors.append(f"layout: source file not found: '{source_str}'")
                if src_path.is_symlink():
                    errors.append(f"layout: source is a symlink: '{source_str}'")

        layout_sources = set(str(v) for v in layout.values())
        for sf in static_files:
            if sf not in layout_sources:
                errors.append(f"static_files: '{sf}' not referenced in layout")

    if errors:
        msg = f"Config validation failed for '{env_name}':\n"
        msg += "\n".join(f"  - {e}" for e in errors)
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# Difficulty parsing
# ---------------------------------------------------------------------------

def parse_difficulty(levels_str: str, axes_def: list) -> Dict[str, str]:
    levels = [lv.strip().lower() for lv in levels_str.split(",")]
    if len(levels) != len(axes_def):
        print(f"ERROR: Expected {len(axes_def)} difficulty values, got {len(levels)}")
        print(f"  Axes: {[a['id'] for a in axes_def]}")
        sys.exit(1)
    for lv, ax in zip(levels, axes_def):
        valid = list(ax["levels"].keys())
        if lv not in valid:
            print(f"ERROR: '{lv}' not valid for axis '{ax['id']}'. Options: {valid}")
            sys.exit(1)
    return {ax["id"]: lv for ax, lv in zip(axes_def, levels)}


# ---------------------------------------------------------------------------
# Substitution
# ---------------------------------------------------------------------------

def build_substitutions(levels: Dict[str, str], axes_def: list) -> Dict[str, str]:
    subs: Dict[str, str] = {}
    for ax in axes_def:
        chosen = levels[ax["id"]]
        mapping = ax["levels"][chosen]
        if mapping:
            for placeholder, text in mapping.items():
                key = placeholder.strip("%")
                subs[key] = str(text) if text is not None else ""
    return subs


def resolve_placeholders(
    text: str,
    subs: Dict[str, str],
    source_hint: str = "",
    strict: bool = True,
) -> str:
    unresolved: List[str] = []

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        if key in subs:
            value = subs[key]
            line_start = text.rfind("\n", 0, match.start()) + 1
            prefix = text[line_start:match.start()]
            if "\n" in value and prefix.strip() == "":
                value = value.replace("\n", "\n" + prefix)
            return value
        unresolved.append(key)
        return match.group(0)

    result = re.sub(r"%%([A-Z0-9_]+)%%", replacer, text)

    if unresolved and strict:
        raise ValueError(
            f"Unresolved placeholders in {source_hint!r}: "
            + ", ".join(f"%%{k}%%" for k in sorted(set(unresolved)))
        )
    return result


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def safe_output_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: '{relative}' escapes output directory '{root}'"
        )
    return candidate


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_env(
    env_name: str,
    output_name: str,
    levels: Dict[str, str],
    seed: int = 0,
    allow_unresolved: bool = False,
) -> None:
    strict = not allow_unresolved

    config = load_config(env_name)
    files_dir = find_files_dir(env_name)

    validate_config(config, files_dir, env_name)

    axes_def: list = config["axes"]
    layout: Dict[str, str] = config["layout"]
    static_files: List[str] = config.get("static_files", [])

    subs = build_substitutions(levels, axes_def)
    subs["ENV_NAME"] = output_name
    subs["JUDGE_SEED"] = str(seed)
    subs["SEED"] = str(seed)  # For use in source code templates

    # Merge top-level scoring settings into the substitution table.
    # Example: scoring.pass_threshold -> %%SCORING_PASS_THRESHOLD%%.
    for k, v in (config.get("scoring") or {}).items():
        key = "SCORING_" + str(k).upper()
        subs[key] = str(v)

    # Merge environment-specific constants (with placeholder resolution).
    raw_constants = config.get("constants", {})
    for k, v in raw_constants.items():
        key = k.strip("%")
        resolved = resolve_placeholders(
            str(v), subs, source_hint=f"constant '{k}'", strict=False
        )
        subs[key] = resolved

    # Resolve placeholders inside substitution values themselves. This is
    # required for composed values such as %%TEMP_Q%% containing %%Q_VAR%%,
    # and for constants such as %%PATCHABLE_FILES%% containing %%MODEL_FILE%%.
    for _ in range(30):
        changed = False
        for key, value in list(subs.items()):
            resolved = resolve_placeholders(value, subs, f"substitution {key}", strict=strict)
            if resolved != value:
                subs[key] = resolved
                changed = True
        if not changed:
            break
    else:
        raise ValueError("Recursive placeholder resolution did not converge")

    print(f"Generating '{env_name}' -> '{output_name}'")
    print(f"  Axes: {', '.join(f'{k}={v}' for k, v in levels.items())}")
    print(f"  Judge seed: {seed}")
    print()

    parent = Path(output_name).resolve().parent
    tmpdir = Path(tempfile.mkdtemp(prefix=f".{output_name}_tmp_", dir=parent))

    try:
        for target_rel_raw, source_file_raw in layout.items():
            target_rel = resolve_placeholders(
                str(target_rel_raw), subs, source_hint="layout key", strict=strict
            )
            source_file = resolve_placeholders(
                str(source_file_raw), subs, source_hint="layout value", strict=strict
            )

            target_path = safe_output_path(tmpdir, target_rel)
            
            if source_file.startswith("shared/"):
                source_path = Path(source_file)
            else:
                source_path = files_dir / source_file

            if not source_path.is_file():
                raise FileNotFoundError(f"Source file not found: {source_path}")
            if source_path.is_symlink():
                raise ValueError(f"Symlink in template sources: {source_path}")

            target_path.parent.mkdir(parents=True, exist_ok=True)

            with source_path.open(encoding="utf-8") as f:
                content = f.read()

            if source_file in static_files:
                content = content.replace("%%ENV_NAME%%", output_name)
                content = content.replace("%%JUDGE_SEED%%", str(seed))
            else:
                content = resolve_placeholders(
                    content, subs, source_hint=source_file, strict=strict
                )

            with target_path.open("w", encoding="utf-8") as f:
                f.write(content)

            print(f"  Wrote: {target_rel}")

        for fpath in tmpdir.rglob("*"):
            if fpath.is_symlink():
                raise ValueError(f"Symlink in generated output: {fpath}")

        for fpath in tmpdir.rglob("*"):
            if fpath.is_file() and (
                fpath.suffix == ".sh" or fpath.name in ("submit.py",)
            ):
                fpath.chmod(0o755)

        dest = Path(output_name).resolve()
        if dest.exists():
            shutil.rmtree(dest)
        tmpdir.rename(dest)

    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    print(f"\nEnvironment '{output_name}' generated successfully.")
    print(f"  Run: cd {output_name} && ./run_eval.sh")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate evaluation environments from declarative configs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_env.py --env glyph --list-axes
  python generate_env.py --env glyph --name g1 --difficulty hard,hard,hard,hard,hard --seed 12345
""",
    )
    parser.add_argument("--env", required=True,
                        help="Environment name (glyph | batchnorm_ema | moco)")
    parser.add_argument("--name", default="",
                        help="Output directory name")
    parser.add_argument("--difficulty", default="",
                        help="Comma-separated difficulty levels, one per axis")
    parser.add_argument("--list-axes", action="store_true",
                        help="Print available axes and exit")
    parser.add_argument("--allow-unresolved", action="store_true",
                        help="Warn instead of failing on unresolved placeholders")
    parser.add_argument("--seed", type=int, default=0,
                        help="Seed for hidden test set (allows multiple instances)")
    args = parser.parse_args()

    # Use registry to check if environment exists
    config_path = resolve_env_path(args.env)
    if config_path is None:
        # Fallback: check filesystem
        registry = _load_registry()
        available = sorted(registry.keys())
        print(f"ERROR: Environment '{args.env}' not found")
        if available:
            print(f"  Available: {', '.join(available)}")
        sys.exit(1)
    
    # Verify the config file exists
    if not config_path.is_file():
        registry = _load_registry()
        available = sorted(registry.keys())
        print(f"ERROR: Config for '{args.env}' not found at {config_path}")
        if available:
            print(f"  Available: {', '.join(available)}")
        sys.exit(1)

    config = load_config(args.env)
    axes_def = config["axes"]

    if args.list_axes:
        print(f"Axes for '{args.env}':")
        for i, ax in enumerate(axes_def):
            desc = ax.get("description", "")
            options = ", ".join(ax["levels"].keys())
            print(f"  {i}: {ax['id']}")
            if desc:
                print(f"       {desc}")
            print(f"       Options: {options}")
        return

    if not args.name:
        parser.error("--name is required unless --list-axes is set")
    if not args.difficulty:
        parser.error("--difficulty is required unless --list-axes is set")

    output_resolved = Path(args.name).resolve()
    cwd_resolved = Path.cwd().resolve()
    try:
        output_resolved.relative_to(cwd_resolved)
    except ValueError:
        print(f"ERROR: Output directory '{args.name}' escapes the current directory.")
        sys.exit(1)

    levels = parse_difficulty(args.difficulty, axes_def)

    try:
        generate_env(
            args.env,
            args.name,
            levels,
            seed=args.seed,
            allow_unresolved=args.allow_unresolved,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
