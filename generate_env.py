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


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import generation_manifest as gm  # noqa: E402


def generator_version() -> str:
    """Version stamped into every provenance record.

    Read from ``pyproject.toml`` rather than hardcoded, so a released generator cannot
    be mistaken for a working tree; the git commit distinguishes the two.
    """
    version = "0.0.0-unknown"
    try:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return version
    match = re.search(r"""^version\s*=\s*["']([^"']+)["']""", text, re.MULTILINE)
    if match:
        version = match.group(1)
    return version


def _git_commit() -> Optional[str]:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except Exception:
        return None
    return proc.stdout.strip() or None


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

    renderer_name = config.get("renderer")
    if renderer_name:
        renderer_path = files_dir / str(renderer_name)
        if not renderer_path.is_file():
            errors.append(f"renderer: file not found: '{renderer_name}'")
        elif renderer_path.is_symlink():
            errors.append(f"renderer: file is a symlink: '{renderer_name}'")

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

    errors.extend(validate_intervention_blocks(config, env_name))

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
# Renderer hooks
# ---------------------------------------------------------------------------

def _run_renderer(files_dir: Path, renderer_name: str, subs: Dict[str, str]) -> Dict[str, str]:
    """Run an environment-specific deterministic renderer hook.

    Opt-in via ``renderer: <file>`` in the environment config (path relative
    to the env's ``files/`` directory). The hook module must define
    ``render(subs: dict) -> dict``; the returned mapping is merged into the
    placeholder table (values may themselves contain placeholders, resolved
    by the normal recursive pass).

    The hook must be a pure function of ``subs`` (seeded randomness only):
    its output is baked into generated instances, and judges may re-derive
    it to check provenance.
    """
    import importlib.util

    renderer_path = files_dir / renderer_name
    if not renderer_path.is_file():
        raise FileNotFoundError(f"renderer not found: {renderer_path}")
    if renderer_path.is_symlink():
        raise ValueError(f"renderer is a symlink: {renderer_path}")
    spec = importlib.util.spec_from_file_location(
        f"env_renderer_{renderer_path.stem}", renderer_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load renderer module: {renderer_path}")
    module = importlib.util.module_from_spec(spec)
    # Allow the renderer to import sibling modules (e.g. the env's core).
    sys.path.insert(0, str(files_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    if not hasattr(module, "render"):
        raise ValueError(f"renderer module {renderer_name!r} must define render(subs)")
    rendered = module.render(dict(subs))
    if not isinstance(rendered, dict):
        raise ValueError("renderer must return a dict of placeholder mappings")
    for key in rendered:
        if not re.fullmatch(r"[A-Z0-9_]+", str(key)):
            raise ValueError(
                f"renderer returned invalid placeholder name {key!r} "
                "(keys must match [A-Z0-9_]+)"
            )
    return {str(k): str(v) for k, v in rendered.items()}


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


# ---------------------------------------------------------------------------
# Causal interventions
# ---------------------------------------------------------------------------
#
# An intervention is mechanically just what a difficulty axis already is: a set of
# placeholder overrides, optionally a layout override, optionally a rename pass
# over the generated tree.  The difference is declarative - each one states what
# must stay the same (``equivalence``) and what the measurement should do
# (``expect``) - which is what turns "the model scored 0.73" into "the model tracked
# the presentation rather than the invariant".

_TAXONOMY: Optional[Dict[str, dict]] = None

_TAXONOMY_RELATIVE_PATH = "envs/interventions.yaml"

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_intervention_taxonomy() -> Dict[str, dict]:
    """Global intervention vocabulary: ids and their declarations."""
    global _TAXONOMY
    if _TAXONOMY is not None:
        return _TAXONOMY
    path = Path(_TAXONOMY_RELATIVE_PATH)
    if not path.is_file():
        path = ROOT / "envs" / "interventions.yaml"
    taxonomy: Dict[str, dict] = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = data.get("interventions") or {}
        if isinstance(raw, dict):
            taxonomy = {str(key): dict(value or {}) for key, value in raw.items()}
    _TAXONOMY = taxonomy
    return _TAXONOMY


def reset_taxonomy_cache() -> None:
    """Test hook: the taxonomy is read once per process."""
    global _TAXONOMY
    _TAXONOMY = None


def validate_intervention_blocks(config: dict, env_name: str) -> List[str]:
    """Structural checks for ``interventions:``, ``renameable_tokens:`` and axis ``class:``."""
    errors: List[str] = []

    for axis in config.get("axes") or []:
        if not isinstance(axis, dict):
            continue
        axis_class = axis.get("class")
        if axis_class is not None and axis_class not in gm.AXIS_CLASSES:
            errors.append(
                f"axes '{axis.get('id')}': class {axis_class!r} must be one of "
                + ", ".join(gm.AXIS_CLASSES)
            )

    tokens = config.get("renameable_tokens")
    if tokens is not None:
        if not isinstance(tokens, list) or not tokens:
            errors.append("'renameable_tokens' must be a non-empty list when present")
        else:
            for token in tokens:
                if not isinstance(token, str) or not _IDENTIFIER_RE.fullmatch(token):
                    errors.append(
                        f"renameable_tokens: {token!r} is not a plain identifier "
                        "(renaming is done by word boundary, so partial names are unsafe)"
                    )

    block = config.get("interventions")
    if block is None:
        return errors
    if not isinstance(block, dict):
        errors.append("'interventions' must be a mapping of intervention id -> implementation")
        return errors

    taxonomy = load_intervention_taxonomy()
    for iid, impl in block.items():
        where = f"interventions '{iid}'"
        if not isinstance(impl, dict):
            errors.append(f"{where}: implementation must be a mapping")
            continue
        if iid not in taxonomy:
            errors.append(
                f"{where}: not in the taxonomy ({_TAXONOMY_RELATIVE_PATH}); known ids: "
                + ", ".join(sorted(taxonomy) or ["(none)"])
            )
        for field, allowed in (
            ("equivalence", gm.EQUIVALENCE_CLASSES),
            ("expect", gm.EXPECTATIONS),
            ("mechanism", gm.MECHANISMS),
        ):
            if impl.get(field) is not None and impl[field] not in allowed:
                errors.append(
                    f"{where}: {field} {impl[field]!r} must be one of " + ", ".join(allowed)
                )
        defect = impl.get("defect_class")
        if defect is not None and defect not in gm.DEFECT_CLASSES:
            errors.append(
                f"{where}: defect_class {defect!r} must be one of " + ", ".join(gm.DEFECT_CLASSES)
            )
        for key in (impl.get("substitutions") or {}):
            name = gm.strip_placeholders(str(key))
            if not re.fullmatch(r"[A-Z0-9_]+", name):
                errors.append(f"{where}: substitution key {key!r} is not a %%PLACEHOLDER%% name")
        for payload in ("substitutions", "layout"):
            value = impl.get(payload)
            if value is not None and not isinstance(value, dict):
                errors.append(f"{where}: '{payload}' must be a mapping")
        if not any(
            impl.get(payload)
            for payload in ("substitutions", "layout")
        ) and str(impl.get("mechanism") or taxonomy.get(iid, {}).get("mechanism")) != "rename":
            errors.append(
                f"{where}: declares no substitutions and no layout override - it would "
                "generate a twin identical to its base, which is a config bug, not an experiment"
            )

    return errors


def parse_intervention_ids(raw: str) -> List[str]:
    """Parse ``--interventions`` into an ordered, de-duplicated id list."""
    if not raw or not raw.strip():
        return []
    requested: List[str] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" in item or ":" in item:
            raise ValueError(
                f"intervention {item!r}: variants (id=value) are not implemented; an "
                "intervention id selects the single overlay its environment declares"
            )
        if item not in requested:
            requested.append(item)
    return requested


def resolve_interventions(
    env_name: str,
    requested: List[str],
    config: dict,
    taxonomy: Optional[Dict[str, dict]] = None,
) -> List[dict]:
    """Turn requested ids into concrete overlays for one environment.

    Every failure here is an error rather than a warning.  In particular, asking an
    environment for an intervention it has not implemented must not produce a twin
    that is secretly identical to its base: that twin would be scored as evidence of
    invariance.
    """
    if taxonomy is None:
        taxonomy = load_intervention_taxonomy()
    implemented = config.get("interventions") or {}
    overlays: List[dict] = []

    for iid in requested:
        entry = taxonomy.get(iid)
        if entry is None:
            raise ValueError(
                f"unknown intervention '{iid}'. Taxonomy ids: "
                + (", ".join(sorted(taxonomy)) or "(none declared)")
            )
        if iid not in implemented:
            raise ValueError(
                f"environment '{env_name}' does not implement intervention '{iid}'. "
                f"Implemented here: {', '.join(sorted(implemented)) or '(none)'}. "
                "This is refused rather than skipped: an inert overlay reported as an "
                "invariance test is indistinguishable from an agent that genuinely "
                "ignored the presentation."
            )
        impl = dict(implemented[iid] or {})

        # equivalence/expect/defect_class are the epistemic claim and are fixed by
        # the taxonomy; `mechanism` is only how an environment realizes that claim,
        # so moco may rename through the substitution table while glyph, which has
        # no name placeholders, renames through the tree-wide pass.
        for field in ("equivalence", "expect"):
            local, global_value = impl.get(field), entry.get(field)
            if local is None or global_value is None:
                continue
            if str(local) != str(global_value):
                raise ValueError(
                    f"{env_name}: intervention '{iid}' declares {field}={local!r} but the "
                    f"taxonomy fixes {global_value!r}. An environment may not redefine what "
                    "must stay invariant - that is the claim the experiment is testing."
                )

        mechanism = str(impl.get("mechanism") or entry.get("mechanism") or "substitution")
        substitutions: Dict[str, str] = {}
        for key, value in (impl.get("substitutions") or {}).items():
            name = gm.strip_placeholders(str(key))
            if not re.fullmatch(r"[A-Z0-9_]+", name):
                raise ValueError(
                    f"{env_name}: intervention '{iid}' substitution key {key!r} is not a "
                    "%%PLACEHOLDER%% name"
                )
            substitutions[name] = "" if value is None else str(value)
        layout = {
            str(key): str(value)
            for key, value in (impl.get("layout") or {}).items()
        }
        rename_tokens: List[str] = []
        if mechanism == "rename":
            rename_tokens = [
                str(token)
                for token in (impl.get("renameable_tokens") or config.get("renameable_tokens") or [])
            ]
            if not rename_tokens:
                raise ValueError(
                    f"{env_name}: intervention '{iid}' uses mechanism 'rename' but declares no "
                    "renameable_tokens; renaming arbitrary identifiers across the tree can "
                    "rewrite a judge-side string check and look like a clean rename"
                )
        if not substitutions and not layout and not rename_tokens:
            raise ValueError(
                f"{env_name}: intervention '{iid}' resolves to an empty overlay (inert by "
                "construction)"
            )

        overlays.append(
            {
                "id": iid,
                "environment": env_name,
                "mechanism": mechanism,
                "equivalence": str(impl.get("equivalence") or entry.get("equivalence") or ""),
                "expect": str(impl.get("expect") or entry.get("expect") or "unspecified"),
                "defect_class": impl.get("defect_class", entry.get("defect_class")),
                "proof": str(entry.get("proof") or "unverified"),
                "description": " ".join(str(entry.get("description") or "").split()),
                "substitutions": substitutions,
                "layout": layout,
                "renameable_tokens": rename_tokens,
                "renames": {},
            }
        )
    return overlays


def _alias_for(token: str, seed: int, intervention_id: str, index: int) -> str:
    digest = gm.sha256_text(f"{token}:{seed}:{intervention_id}:{index}")[:8]
    return f"Renamed{index}_{digest}"


def apply_rename_transform(tree: Path, overlays: List[dict], seed: int) -> List[dict]:
    """Rename every declared identifier across the generated tree, deterministically.

    Applies to both agent and judge sides, which is what keeps the oracle valid: a
    rename that reached only the workspace would break the judge's ``getattr`` string.
    Text files only - environments ship binary payloads (``rope`` ships a PDF).
    """
    active = [overlay for overlay in overlays if overlay.get("mechanism") == "rename"]
    if not active:
        return []

    files = [path for path in sorted(tree.rglob("*")) if path.is_file() and gm.is_text_path(path)]
    contents = {path: path.read_text(encoding="utf-8") for path in files}

    for overlay in active:
        renames: Dict[str, dict] = {}
        for index, token in enumerate(overlay["renameable_tokens"]):
            if not _IDENTIFIER_RE.fullmatch(token):
                raise ValueError(
                    f"renameable_tokens: {token!r} is not a plain identifier; refusing to "
                    "rename substrings"
                )
            alias = _alias_for(token, seed, str(overlay["id"]), index)
            if any(alias in text for text in contents.values()):
                raise ValueError(
                    f"rename alias {alias!r} already occurs in the generated tree; the twin "
                    "comparison could not be inverted, so generation is refused"
                )
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])")
            touched = 0
            occurrences = 0
            for path, text in list(contents.items()):
                replacement, count = pattern.subn(alias, text)
                if count:
                    contents[path] = replacement
                    touched += 1
                    occurrences += count
            renames[token] = {
                "alias": alias,
                "occurrences": occurrences,
                "files_touched": touched,
            }
        overlay["renames"] = renames

    for path, text in contents.items():
        original = path.read_text(encoding="utf-8")
        if original != text:
            path.write_text(text, encoding="utf-8")

    return [overlay for overlay in active]


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

def config_path_for(env_name: str) -> Path:
    """Registry-resolved path of an environment config (used for provenance hashing)."""
    resolved = resolve_env_path(env_name)
    if resolved is not None:
        return resolved
    return Path("envs") / env_name / "config.yaml"


def prepare_generation(
    env_name: str,
    output_name: str,
    levels: Dict[str, str],
    seed: int = 0,
    allow_unresolved: bool = False,
    interventions: Optional[List[str]] = None,
) -> dict:
    """Resolve the full substitution table and layout for one family member.

    ``tools/twin_check.py`` calls this same function instead of parsing generated
    files: comparing twins only proves something about generation if the comparison
    goes through the code path that produced them.
    """
    strict = not allow_unresolved

    config = load_config(env_name)
    files_dir = find_files_dir(env_name)
    validate_config(config, files_dir, env_name)
    overlays = resolve_interventions(env_name, list(interventions or []), config)

    axes_def: list = config["axes"]
    layout: Dict[str, str] = dict(config["layout"])
    static_files: List[str] = list(config.get("static_files", []))

    subs = build_substitutions(levels, axes_def)
    # ENV_NAME is the image/artifact prefix used by run_eval.sh, so it must be the
    # instance's own name and not the path it happens to live in; the family
    # expander generates members into subdirectories of one family.
    name_label = Path(output_name).name
    subs["ENV_NAME"] = name_label
    subs["JUDGE_SEED"] = str(seed)
    subs["SEED"] = str(seed)

    # Interventions are applied before constants and before the renderer hook, so
    # that derived values (PATCHABLE_FILES, the baked task text) inherit them.
    # Applying them afterwards would allow an intervention to rename a file the
    # judge never looks for.
    for overlay in overlays:
        subs.update(overlay["substitutions"])
        layout.update(overlay["layout"])

    for key, value in (config.get("scoring") or {}).items():
        subs["SCORING_" + str(key).upper()] = str(value)

    raw_constants = config.get("constants", {})
    for key, value in raw_constants.items():
        name = key.strip("%")
        resolved = resolve_placeholders(
            str(value), subs, source_hint=f"constant '{key}'", strict=False
        )
        subs[name] = resolved

    # A layout override may drop a target that a static file was declared against.
    layout_sources = {str(value) for value in layout.values()}
    for static_file in static_files:
        if static_file not in layout_sources:
            raise ValueError(
                f"{env_name}: an intervention removed the layout entry for static file "
                f"'{static_file}'; static files cannot be dropped by an overlay"
            )

    renderer_name = config.get("renderer")
    if renderer_name:
        rendered = _run_renderer(files_dir, str(renderer_name), subs)
        for key, value in rendered.items():
            subs[key] = value

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

    return {
        "env_name": env_name,
        "output_name": name_label,
        "name_label": name_label,
        "levels": dict(levels),
        "seed": int(seed),
        "config": config,
        "config_path": config_path_for(env_name),
        "files_dir": files_dir,
        "subs": subs,
        "layout": layout,
        "static_files": static_files,
        "overlays": overlays,
        "strict": strict,
    }


def _judge_source_hashes(destination: Path) -> Dict[str, str]:
    judge_dir = destination / "judge"
    if not judge_dir.is_dir():
        return {}
    return {
        f"judge/{rel}": digest for rel, digest in gm.file_hashes(judge_dir).items()
    }


def _latent_spec_sha256(destination: Path) -> Optional[str]:
    """Hash of the judge-side baked instance spec, when the environment bakes one.

    Only ``epistemic_games`` does today. Where it exists, task identity is structural
    rather than nominal, so ``pair_id`` is computed from it and the basis recorded as
    ``latent_spec``; everywhere else the fallback is stated instead of hidden.
    """
    spec = destination / "judge" / "instance_spec.py"
    if not spec.is_file():
        return None
    return gm.sha256_text(spec.read_text(encoding="utf-8"))


def generate_env(
    env_name: str,
    output_name: str,
    levels: Dict[str, str],
    seed: int = 0,
    allow_unresolved: bool = False,
    interventions: Optional[List[str]] = None,
    parent_generation_id: Optional[str] = None,
    emit_manifest: bool = True,
) -> dict:
    prepared = prepare_generation(
        env_name,
        output_name,
        levels,
        seed=seed,
        allow_unresolved=allow_unresolved,
        interventions=interventions,
    )

    strict = prepared["strict"]
    subs = prepared["subs"]
    layout = prepared["layout"]
    static_files = prepared["static_files"]
    files_dir = prepared["files_dir"]
    overlays = prepared["overlays"]
    config_path: Path = prepared["config_path"]
    name_label: str = prepared["name_label"]

    print(f"Generating '{env_name}' -> '{output_name}'")
    print(f"  Axes: {', '.join(f'{k}={v}' for k, v in levels.items())}")
    if overlays:
        print(
            "  Interventions: "
            + ", ".join(
                f"{overlay['id']} ({overlay['equivalence']}, expect {overlay['expect']})"
                for overlay in overlays
            )
        )
    print(f"  Judge seed: {seed}")
    print()

    parent = Path(output_name).resolve().parent
    # The instance label, not the full path: an absolute output name would otherwise
    # put separators in the mkdtemp prefix and nest the temporary tree inside itself.
    tmpdir = Path(tempfile.mkdtemp(prefix=f".{name_label}_tmp_", dir=parent))

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
                content = content.replace("%%ENV_NAME%%", name_label)
                content = content.replace("%%JUDGE_SEED%%", str(seed))
            else:
                content = resolve_placeholders(
                    content, subs, source_hint=source_file, strict=strict
                )

            with target_path.open("w", encoding="utf-8") as f:
                f.write(content)

            print(f"  Wrote: {target_rel}")

        if overlays:
            apply_rename_transform(tmpdir, overlays, seed)
            for overlay in overlays:
                touched = sum(
                    int(info["occurrences"]) for info in (overlay.get("renames") or {}).values()
                )
                if touched:
                    print(f"  Renamed: {overlay['id']} ({touched} occurrences)")

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

    manifest: Dict[str, object] = {}
    if emit_manifest:
        manifest = gm.build_manifest(
            env=env_name,
            output_name=name_label,
            tree_root=str(dest),
            config_path=str(config_path),
            config_sha256=gm.sha256_text(config_path.read_text(encoding="utf-8")),
            seed=seed,
            difficulty_vector=levels,
            interventions=[_manifest_overlay(overlay) for overlay in overlays],
            generator_version=generator_version(),
            judge_sources=_judge_source_hashes(dest),
            latent_spec_sha256=_latent_spec_sha256(dest),
            parent_generation_id=parent_generation_id,
            repository={"commit": _git_commit()},
            substitution_snapshot=subs,
        )
        written = gm.write_manifest(dest, manifest)
        print(f"\n  generation_id: {manifest['generation_id']}")
        print(f"  pair_id:       {manifest['pair_id']} ({manifest['pair_id_basis']})")
        print(f"  manifest:      {written}")

    print(f"\nEnvironment '{output_name}' generated successfully.")
    print(f"  Run: cd {output_name} && ./run_eval.sh")
    return manifest


def _manifest_overlay(overlay: dict) -> dict:
    """Manifest-facing view of an overlay: the declaration plus what it changed."""
    return {
        "id": overlay["id"],
        "environment": overlay["environment"],
        "mechanism": overlay["mechanism"],
        "equivalence": overlay["equivalence"],
        "expect": overlay["expect"],
        "defect_class": overlay["defect_class"],
        "proof": overlay["proof"],
        "description": overlay["description"],
        "substitutions": dict(overlay["substitutions"]),
        "layout": dict(overlay["layout"]),
        "renames": {
            token: {"alias": info["alias"], "occurrences": info["occurrences"]}
            for token, info in (overlay.get("renames") or {}).items()
        },
    }




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
    parser.add_argument("--list-interventions", action="store_true",
                        help="Print the intervention taxonomy and which ids this env implements")
    parser.add_argument("--allow-unresolved", action="store_true",
                        help="Warn instead of failing on unresolved placeholders")
    parser.add_argument("--seed", type=int, default=0,
                        help="Seed for hidden test set (allows multiple instances)")
    parser.add_argument("--interventions", default="",
                        help="Comma-separated causal intervention ids to apply on top of "
                             "the difficulty vector (see --list-interventions)")
    parser.add_argument("--parent-generation-id", default=None,
                        help="Record lineage: the generation this instance was derived from")
    parser.add_argument("--no-manifest", action="store_true",
                        help="Do not write generation.json (discards provenance; not for "
                             "results that will be reported)")
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
            if ax.get("class"):
                print(
                    f"       Class: {ax['class']} (what this axis moves: presentation, "
                    "observation, evaluator or task)"
                )
        return

    if args.list_interventions:
        taxonomy = load_intervention_taxonomy()
        implemented = (config.get("interventions") or {})
        print(f"Interventions for '{args.env}': {len(implemented)} of {len(taxonomy)} taxonomy ids")
        for iid in sorted(set(taxonomy) | set(implemented)):
            entry = taxonomy.get(iid, {})
            impl = implemented.get(iid)
            status = "implemented" if impl is not None else "not implemented here"
            print(f"  {iid}  [{status}]")
            print(f"       equivalence: {entry.get('equivalence', '?')}   expect: {entry.get('expect', '?')}"
                  f"   mechanism: {entry.get('mechanism', '?')}   proof: {entry.get('proof', 'unverified')}")
            if entry.get("defect_class"):
                print(f"       defect_class: {entry['defect_class']}")
            description = " ".join(str(entry.get("description") or "").split())
            if description:
                print(f"       {description}")
        if not implemented:
            print(f"  (no interventions implemented: {args.env} cannot be a family member yet)")
        return

    if not args.name:
        parser.error("--name is required unless --list-axes/--list-interventions is set")
    if not args.difficulty:
        parser.error("--difficulty is required unless --list-axes/--list-interventions is set")

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
            interventions=parse_intervention_ids(args.interventions),
            parent_generation_id=args.parent_generation_id,
            emit_manifest=not args.no_manifest,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
