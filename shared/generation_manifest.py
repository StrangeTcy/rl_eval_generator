"""Generation provenance for generated environments.

Every directory ``generate_env.py`` writes gets a ``generation.json`` recording the
exact inputs that produced it and a content hash of the tree it produced.  This is
the artifact the causal-experiment layer is built on: without it, two generated
directories cannot be told apart from a copy, a stale checkout, or a hand edit, and
"the agent was invariant under this intervention" would be a claim about bytes
nobody re-checked.

Two identifiers, deliberately different (decision 13 in
``docs/decisions/2026-10-08-causal-experiment-layer.md``):

``generation_id``
    Identity of **one artifact**: environment, config hash, difficulty vector,
    intervention vector, seed, transforms, generator version, and the tree hash.
    Two runs that differ in any of these are different artifacts.

``pair_id``
    Identity of the **task** an artifact presents.  It deliberately excludes
    presentation-layer interventions, because the experiment asks whether behavior
    survives transformations that must not change the task.  Only ``task_changing``
    interventions enter it.  When a latent task spec exists (see item 4) its hash is
    the identity; otherwise the key falls back to the base case id and the fallback
    is *recorded*, never silent.

Stdlib only, and no generated code is imported here: the module has to be usable
from ``tools/`` and from tests without Docker, torch, or a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Iterable, Mapping

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_NAME = "generation.json"
FAMILY_MANIFEST_NAME = "family_manifest.json"

#: ``equivalence`` answers "what must stay the same".
EQUIVALENCE_CLASSES = (
    "semantically_equivalent",
    "observation_changing",
    "evaluator_changing",
    "task_changing",
)
#: ``expect`` answers "what should the measured behavior do".
EXPECTATIONS = ("invariant", "sensitive", "unspecified")
#: ``defect_class`` answers "what was done to the information" (POTEMKIN A-F, P2.8).
DEFECT_CLASSES = (
    "A_false",
    "B_missing",
    "C_selective",
    "D_provenance",
    "E_multisource",
    "F_drift",
)
#: How an intervention is applied.
MECHANISMS = ("substitution", "layout", "rename")
#: Reused for tagging difficulty axes so presentation knobs are not mistaken for
#: task depth (item 3).
AXIS_CLASSES = ("presentation", "observation", "evaluator", "task")

#: Equivalences that change task identity and therefore enter ``pair_id``.
#: ``observation_changing`` and ``evaluator_changing`` do NOT: the invariant the
#: agent must respect is the same, only the evidence about it or the measurement of
#: it moved.
IDENTITY_CHANGING: frozenset[str] = frozenset({"task_changing"})

_PLACEHOLDER_RE = re.compile(r"%%([A-Za-z0-9_]+)%%")

TEXT_SUFFIXES = frozenset(
    {
        ".py", ".pyi", ".md", ".sh", ".txt", ".json", ".yaml", ".yml", ".csv",
        ".tsv", ".tex", ".patch", ".diff", ".cfg", ".ini", ".toml", ".in", ".pyi",
    }
)
TEXT_NAMES = frozenset({"Dockerfile", "Dockerfile.agent", "Dockerfile.judge", "Makefile", ".gitignore"})


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_text_path(path: Path) -> bool:
    """Text files are hash-decodable and canonicalizable; everything else is bytes.

    Binary payloads (``rope`` ships a real PDF) must never be rewritten by the
    rename transform, and must still be counted in the tree hash.
    """
    if path.name in TEXT_NAMES:
        return True
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
    except OSError:
        return False
    return b"\0" not in chunk and _is_decodable(chunk)


def _is_decodable(chunk: bytes) -> bool:
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def iter_files(root: Path) -> list[str]:
    """Sorted relative posix paths of every file under ``root`` (manifest excluded)."""
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == MANIFEST_NAME:
            continue
        out.append(rel)
    return out


def file_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for rel in iter_files(root):
        data = (root / rel).read_bytes()
        result[rel] = sha256_bytes(data)
    return result


def tree_sha256(root: Path) -> str:
    """Hash over ``path:content`` pairs, so a rename of a file changes the tree."""
    lines = [f"{rel}:{digest}" for rel, digest in sorted(file_hashes(root).items())]
    return sha256_text("\n".join(lines))


def hash_texts(mapping: Mapping[str, str]) -> str:
    lines = [f"{key}:{value}" for key, value in sorted(mapping.items())]
    return sha256_text("\n".join(lines))


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------

def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generation_id(
    *,
    env: str,
    config_path: str,
    config_sha256: str,
    seed: int,
    difficulty_vector: Mapping[str, str],
    intervention_vector: Iterable[Mapping[str, Any]],
    generator_version: str,
    tree_sha256_value: str,
) -> str:
    payload = {
        "env": env,
        "config_path": config_path,
        "config_sha256": config_sha256,
        "seed": int(seed),
        "difficulty_vector": dict(sorted(difficulty_vector.items())),
        "intervention_vector": sorted(
            (_intervention_key(item) for item in intervention_vector),
        ),
        "generator_version": generator_version,
        "tree_sha256": tree_sha256_value,
    }
    return "G" + sha256_text(_canonical_json(payload))[:16]


def pair_id(
    *,
    env: str,
    seed: int,
    difficulty_vector: Mapping[str, str],
    intervention_vector: Iterable[Mapping[str, Any]],
    latent_spec_sha256: str | None = None,
) -> tuple[str, str]:
    """Return ``(pair_id, basis)``; basis is ``latent_spec`` or ``case_id_fallback``.

    The fallback is a real, recorded state of the world, not a failure: until item 4
    lands a config-wide ``latent_factors:`` block, there is no structural task
    identity to hash for 33 environments.
    """
    identity = sorted(
        _intervention_key(item)
        for item in intervention_vector
        if str(item.get("equivalence") or "") in IDENTITY_CHANGING
    )
    payload = {
        "env": env,
        "seed": int(seed),
        "difficulty_vector": dict(sorted(difficulty_vector.items())),
        "identity_interventions": identity,
    }
    if latent_spec_sha256:
        payload["latent_spec_sha256"] = latent_spec_sha256
        return "P" + sha256_text(_canonical_json(payload))[:16], "latent_spec"
    return "P" + sha256_text(_canonical_json(payload))[:16], "case_id_fallback"


def _intervention_key(item: Mapping[str, Any]) -> str:
    if isinstance(item, str):
        return item
    return f"{item.get('id')}={_canonical_json(item.get('declared') or {})}"


def base_case_id(env: str, difficulty_vector: Mapping[str, str], seed: int) -> str:
    """Same shape as ``run_suite`` case ids so twins stay greppable in campaign logs."""
    parts = "_".join(f"{key}={value}" for key, value in sorted(difficulty_vector.items()))
    return f"{env}__{parts}__seed-{seed}"


# ---------------------------------------------------------------------------
# manifests
# ---------------------------------------------------------------------------

def build_manifest(
    *,
    env: str,
    output_name: str,
    tree_root: Path | str,
    config_path: str,
    config_sha256: str,
    seed: int,
    difficulty_vector: Mapping[str, str],
    interventions: Sequence[Mapping[str, Any]] | None = None,
    generator_version: str,
    judge_sources: Mapping[str, str],
    latent_spec_sha256: str | None = None,
    parent_generation_id: str | None = None,
    repository: Mapping[str, Any] | None = None,
    substitution_snapshot: Mapping[str, str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the manifest for a generated environment (tree must already be final).

    ``output_name`` is the instance label baked into the environment, while
    ``tree_root`` is where the directory actually sits on disk.  They are different
    things and conflating them makes provenance depend on the path a family happened
    to be generated under.
    """
    interventions = list(interventions or [])
    root = Path(tree_root)
    tree_hash = tree_sha256(root)
    gid = generation_id(
        env=env,
        config_path=config_path,
        config_sha256=config_sha256,
        seed=seed,
        difficulty_vector=difficulty_vector,
        intervention_vector=interventions,
        generator_version=generator_version,
        tree_sha256_value=tree_hash,
    )
    pid, basis = pair_id(
        env=env,
        seed=seed,
        difficulty_vector=difficulty_vector,
        intervention_vector=interventions,
        latent_spec_sha256=latent_spec_sha256,
    )
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generation_id": gid,
        "parent_generation_id": parent_generation_id,
        "pair_id": pid,
        "pair_id_basis": basis,
        "base_case_id": base_case_id(env, difficulty_vector, seed),
        "generator_version": generator_version,
        "environment": env,
        "environment_family": family_of(config_path),
        "output_name": str(output_name),
        "seed": int(seed),
        "config_path": config_path,
        "config_sha256": config_sha256,
        "difficulty_vector": dict(sorted(difficulty_vector.items())),
        "interventions": interventions,
        "expected_invariances": sorted(
            {str(item["id"]) for item in interventions if item.get("expect") == "invariant"}
        ),
        "expected_differences": sorted(
            {str(item["id"]) for item in interventions if item.get("expect") == "sensitive"}
        ),
        "tree_sha256": tree_hash,
        "files": file_hashes(root),
        "judge_sha256": hash_texts(judge_sources),
        "judge_files": dict(sorted(judge_sources.items())),
        "latent_spec_sha256": latent_spec_sha256,
        "latent_spec": "unavailable" if latent_spec_sha256 is None else "declared",
        "substitution_snapshot_sha256": (
            hash_texts(substitution_snapshot) if substitution_snapshot is not None else None
        ),
        "repository": dict(repository or {}),
    }
    manifest.update(dict(extra or {}))
    return manifest


def family_of(config_path: str) -> str:
    """Family = the path under ``envs/`` that groups the environment.

    ``envs/cat_theo/tensor_functor/config.yaml`` -> ``cat_theo``;
    ``envs/moco/config.yaml`` -> ``moco``.  Read from the recorded config path
    rather than a lookup table, so a new nested family needs no code change.
    """
    parts = [part for part in str(config_path).replace("\\", "/").split("/") if part]
    try:
        index = parts.index("envs")
    except ValueError:
        return "unknown"
    tail = parts[index + 1 : -1]
    if len(tail) >= 2:
        return "/".join(tail[:-1])
    if len(tail) == 1:
        return tail[0]
    return "flat"


def write_manifest(directory: Path | str, manifest: Mapping[str, Any]) -> Path:
    target = Path(directory) / MANIFEST_NAME
    _atomic_write_text(target, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return target


def read_manifest(directory: Path | str) -> dict[str, Any]:
    path = Path(directory) / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {MANIFEST_NAME} in {directory}")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_manifest(
    directory: Path | str,
    *,
    config_root: Path | str | None = None,
    generator_version: str | None = None,
) -> tuple[bool, list[str]]:
    """Recompute the claims in a manifest; used before grading and in CI.

    Checks, in order of what they catch: the tree still matches the recorded hash
    (post-generation edits), every recorded file hash matches, and - when a repo
    root is given - the config that produced this environment has not drifted.
    A mismatch is not an agent failure; it means the artifact cannot be attributed.
    """
    root = Path(directory)
    errors: list[str] = []
    manifest = read_manifest(root)

    recorded = manifest.get("files") or {}
    actual = file_hashes(root)
    for rel, digest in recorded.items():
        if rel not in actual:
            errors.append(f"recorded file missing: {rel}")
        elif actual[rel] != digest:
            errors.append(f"file content differs from manifest: {rel}")
    for rel in actual:
        if rel not in recorded:
            errors.append(f"file not present in manifest: {rel}")

    if manifest.get("tree_sha256") != tree_sha256(root):
        errors.append("tree_sha256 mismatch")

    config_path = manifest.get("config_path")
    if config_root is not None and config_path:
        candidate = Path(config_root) / config_path
        if not candidate.is_file():
            errors.append(f"config not found for recompute: {config_path}")
        elif sha256_bytes(candidate.read_bytes()) != manifest.get("config_sha256"):
            errors.append(
                "config_sha256 mismatch: the environment config changed after generation, "
                "so this artifact's claims describe a different generator state"
            )

    if generator_version is not None and manifest.get("generator_version") != generator_version:
        errors.append(
            f"generator_version mismatch: manifest {manifest.get('generator_version')!r} "
            f"vs {generator_version!r}"
        )

    recomputed = generation_id(
        env=str(manifest.get("environment")),
        config_path=str(manifest.get("config_path")),
        config_sha256=str(manifest.get("config_sha256")),
        seed=int(manifest.get("seed", 0)),
        difficulty_vector=manifest.get("difficulty_vector") or {},
        intervention_vector=manifest.get("interventions") or [],
        generator_version=str(manifest.get("generator_version")),
        tree_sha256_value=str(manifest.get("tree_sha256")),
    )
    if recomputed != manifest.get("generation_id"):
        errors.append("generation_id does not match its recorded inputs")

    recomputed_pair, recomputed_basis = pair_id(
        env=str(manifest.get("environment")),
        seed=int(manifest.get("seed", 0)),
        difficulty_vector=manifest.get("difficulty_vector") or {},
        intervention_vector=manifest.get("interventions") or [],
        latent_spec_sha256=manifest.get("latent_spec_sha256"),
    )
    if recomputed_pair != manifest.get("pair_id"):
        errors.append("pair_id does not match its recorded inputs")
    if recomputed_basis != manifest.get("pair_id_basis"):
        errors.append("pair_id_basis does not match its recorded inputs")

    return (not errors, errors)


def _atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent), delete=False, suffix=".tmp"
    )
    try:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    Path(handle.name).replace(target)


def strip_placeholders(name: str) -> str:
    match = _PLACEHOLDER_RE.fullmatch(str(name).strip())
    return match.group(1) if match else str(name).strip()


def assert_clean_provenance_text(text: str, *, where: str) -> None:
    """Manifests must not carry raw ``%%NAME%%`` tokens.

    A generated environment is scanned for unresolved placeholders by the existing
    test suite; the manifest inside it is part of that tree, so an unresolved token
    recorded here would either break the suite or hide a substitution bug.
    """
    leaked = sorted(set(_PLACEHOLDER_RE.findall(text)))
    if leaked:
        raise ValueError(
            f"{where}: unresolved placeholder(s) in provenance record: "
            + ", ".join(f"%%{name}%%" for name in leaked)
        )
