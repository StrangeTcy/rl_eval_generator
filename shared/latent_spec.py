"""Latent task specifications: what a generated instance's task *is* (item 4, PR-C).

Every config declares a ``latent_factors:`` block; at generation time this module
derives ``latent_spec.json`` from the declared factors and the instantiated
substitution table, and the hash of the spec's *identity projection* becomes the
``pair_id`` basis.  That is the promotion decision 13 was waiting on: task identity
stops being the case id (which splits twins that differ only in prose) and becomes
structural (which merges them).

The vocabulary is the generalization of what ``epistemic_games`` already had
(``Instance.to_spec()``, re-derived by the judge):

``task_state``          what the world is: the values that make this instance this task
``causal_mechanism``    the generative mechanism, where one exists; for a template env
                        the mechanism is fixed hand-authored code and the honest value
                        is ``unavailable`` - a derived spec records *which placeholders
                        were instantiated*, which is not a causal model
``observable_state``    the evidence the instance presents, including presentation
                        dress (names, hints, prose): recorded, never identity
``proxy_signal``        what a proxy-chasing agent can read instead of the invariant
                        (visible tests, planted cues)
``evaluator_state``     how the instance is measured: scoring rule, judge-side
                        allowlists, judge file set.  Required in every config, or
                        evaluator-shift twins collide (item 4 -> item 13)
``agent_belief``        not a property of the instance at generation time; always
                        ``unavailable`` here - the trajectory microscope (item 8)
                        approximates it at run time, and says ``not_measurable``
                        where it cannot

Identity rules (the payload ``pair_id`` hashes):

* only ``task_state``, ``causal_mechanism`` and ``evaluator_state`` enter, plus
  environment and seed; an observation-layer twin is the same task under different
  evidence, so nothing in ``observable_state`` or ``proxy_signal`` may split a pair
* values entering identity are canonicalized through the renamings any
  ``semantically_equivalent`` overlay introduced, mapped longest-first with word
  boundaries - the same invertibility rule ``tools/twin_check.py`` enforces on
  trees, applied to values, so a presentation twin cannot move identity through a
  composed constant (``PATCHABLE_FILES`` embeds the renamed file name)
* procedural environments may declare ``source: instance_spec`` with explicit
  ``identity_keys``: a projection of the judge-baked ground truth.  The projection
  is a *declaration* (``declared_by`` stamps who owns it), because choosing which
  keys carry task identity is exactly the kind of claim a scaffold may not make
  silently.  Dotted keys (``hypotheses.level``) select one nested level per entry
  of a mapping.

Stdlib only; no generated or environment code is imported here - the instance spec
is read with ``ast.literal_eval``, never executed.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from shared import generation_manifest as gm

SPEC_NAME = "latent_spec.json"
SPEC_TYPE = "rl_eval_latent_spec"
SPEC_SCHEMA_VERSION = 1
IDENTITY_SCHEMA = "rl_eval_latent_identity/1"

#: The honest value for a factor this environment cannot declare (yet).
UNAVAILABLE = "unavailable"

FACTORS = (
    "task_state",
    "causal_mechanism",
    "observable_state",
    "proxy_signal",
    "evaluator_state",
    "agent_belief",
)
#: Factors whose values define the task.  Everything else describes how the task is
#: presented or measured-adjacent, and must not split a pair.
IDENTITY_FACTORS = ("task_state", "causal_mechanism", "evaluator_state")
#: Factors every config must declare: without evaluator_state, two instances that
#: differ only in how they are graded hash to the same task (item 4 -> item 13).
REQUIRED_FACTORS = ("task_state", "evaluator_state")

DECLARED_BY = ("human", "scaffold_unreviewed")
SOURCES = ("substitutions", "instance_spec")

_PLACEHOLDER_NAME_RE = re.compile(r"[A-Z0-9_]+")
_ATOMIC = re.compile(r"[A-Za-z0-9_]+")


def canonical_json(value: Any) -> str:
    """The one canonical form every hash in this layer is taken over."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _known_placeholders(config: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for axis in config.get("axes") or []:
        if not isinstance(axis, Mapping):
            continue
        for level in (axis.get("levels") or {}).values():
            for key in (level or {}):
                names.add(gm.strip_placeholders(str(key)))
    for key in config.get("constants") or {}:
        names.add(gm.strip_placeholders(str(key)))
    return names


def validate_latent_factors(config: Mapping[str, Any], env_name: str) -> list[str]:
    """Structural checks for the ``latent_factors:`` block (decision item 4).

    The block is required: registry completeness is a checklist, and a config that
    has not declared its task identity keeps falling back to case-id pairing, which
    is the state the decision explicitly removes.
    """
    errors: list[str] = []
    block = config.get("latent_factors")
    if block is None:
        return [
            f"{env_name}: missing 'latent_factors:' block - every config declares what "
            "its task identity is (decision item 4). Starter block: "
            f"python tools/latent_factors_scaffold.py --env {env_name} --write"
        ]
    if not isinstance(block, Mapping):
        return [f"{env_name}: 'latent_factors' must be a mapping"]

    if block.get("declared_by") not in DECLARED_BY:
        errors.append(
            f"{env_name}: latent_factors.declared_by must be one of "
            + ", ".join(DECLARED_BY)
            + " - a mechanical declaration must never be citable as a causal claim"
        )
    if block.get("schema_version") != SPEC_SCHEMA_VERSION:
        errors.append(
            f"{env_name}: latent_factors.schema_version must be {SPEC_SCHEMA_VERSION}"
        )
    factors = block.get("factors")
    if not isinstance(factors, Mapping) or not factors:
        errors.append(f"{env_name}: latent_factors.factors must be a non-empty mapping")
        return errors

    has_renderer = bool(config.get("renderer"))
    known = _known_placeholders(config)
    seen: dict[str, str] = {}
    for fname, fdecl in factors.items():
        where = f"{env_name}: latent_factors.{fname}"
        if fname not in FACTORS:
            errors.append(
                f"{where}: unknown factor; the vocabulary is " + ", ".join(FACTORS)
            )
            continue
        if not isinstance(fdecl, Mapping):
            errors.append(f"{where}: declaration must be a mapping")
            continue
        if UNAVAILABLE in fdecl:
            reason = fdecl[UNAVAILABLE]
            if not isinstance(reason, str) or not reason.strip():
                errors.append(
                    f"{where}: '{UNAVAILABLE}' needs a non-empty reason - a missing "
                    "factor is recorded, never silently dropped"
                )
            extra = sorted(set(fdecl) - {UNAVAILABLE})
            if extra:
                errors.append(
                    f"{where}: '{UNAVAILABLE}' is exclusive; also declares {extra}"
                )
            continue
        source = str(fdecl.get("source") or "substitutions")
        if source not in SOURCES:
            errors.append(f"{where}: source {source!r} must be one of " + ", ".join(SOURCES))
        allowed_keys = {"source", "placeholders", "identity_keys"} | (
            {"scoring", "constants", "judge_files"} if fname == "evaluator_state" else set()
        )
        unknown_keys = sorted(set(fdecl) - allowed_keys)
        if unknown_keys:
            errors.append(f"{where}: unknown declaration keys {unknown_keys}")
        if source == "instance_spec" and not has_renderer:
            errors.append(
                f"{where}: source 'instance_spec' requires a renderer that bakes "
                "judge/instance_spec.py"
            )
        identity_keys = fdecl.get("identity_keys")
        if identity_keys is not None:
            if source != "instance_spec":
                errors.append(
                    f"{where}: identity_keys applies only to source 'instance_spec'"
                )
            elif not isinstance(identity_keys, Sequence) or isinstance(identity_keys, (str, bytes)):
                errors.append(f"{where}: identity_keys must be a list of spec keys")
            else:
                for key in identity_keys:
                    if not isinstance(key, str) or not key.strip():
                        errors.append(f"{where}: identity_keys entries must be non-empty strings")
        placeholders = fdecl.get("placeholders")
        if placeholders is None:
            structural = fname == "evaluator_state" and any(
                key in fdecl for key in ("scoring", "constants", "judge_files")
            )
            if source == "substitutions" and not structural:
                errors.append(
                    f"{where}: source 'substitutions' needs a placeholders list (or "
                    f"declare '{UNAVAILABLE}' with a reason)"
                )
            placeholders = []
        if not isinstance(placeholders, Sequence) or isinstance(placeholders, (str, bytes)):
            errors.append(f"{where}: placeholders must be a list")
            placeholders = []
        for raw in placeholders:
            name = gm.strip_placeholders(str(raw))
            if not _PLACEHOLDER_NAME_RE.fullmatch(name):
                errors.append(f"{where}: placeholder {raw!r} is not a %%PLACEHOLDER%% name")
                continue
            if name in seen:
                errors.append(
                    f"{where}: placeholder {name} is already declared under "
                    f"'{seen[name]}' - one value, one factor, or identity becomes "
                    "ambiguous"
                )
                continue
            seen[name] = fname
            if not has_renderer and name not in known:
                errors.append(
                    f"{where}: placeholder {name} appears in no axis level and no "
                    "constant of this config"
                )
    for required in REQUIRED_FACTORS:
        if required not in factors:
            why = (
                "evaluator-shift twins collide without it (item 4 -> item 13)"
                if required == "evaluator_state"
                else "task identity needs a task_state declaration, even if the honest "
                     "value is 'unavailable' with a reason"
            )
            errors.append(f"{env_name}: latent_factors.factors.{required} is required - {why}")
    return errors


# ---------------------------------------------------------------------------
# presentation canonicalization
# ---------------------------------------------------------------------------

def _value_pattern(value: str) -> re.Pattern[str]:
    escaped = re.escape(value)
    if _ATOMIC.fullmatch(value):
        return re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])")
    return re.compile(escaped)


def compile_identity_rewrites(pairs: Iterable[tuple[str, str]]) -> list[tuple[re.Pattern[str], str]]:
    """(twin value, base value) pairs -> longest-first rewrite rules.

    Mirrors ``tools/twin_check._twin_to_base``: only name-like values are anchored
    at word boundaries, everything else is replaced literally, and the longest twin
    value goes first so ``moco_model.py`` is mapped before ``moco_model``.
    """
    ordered = sorted(
        {(twin, base) for twin, base in pairs if twin and base and twin != base},
        key=lambda item: len(item[0]),
        reverse=True,
    )
    return [(_value_pattern(twin), base) for twin, base in ordered]


def canonicalize(value: Any, rewrites: Sequence[tuple[re.Pattern[str], str]]) -> Any:
    """Map every value a declared presentation overlay introduced back to its base."""
    if isinstance(value, str):
        for pattern, base in rewrites:
            value = pattern.sub(lambda _m: base, value)
        return value
    if isinstance(value, Mapping):
        return {str(key): canonicalize(item, rewrites) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [canonicalize(item, rewrites) for item in value]
    return value


# ---------------------------------------------------------------------------
# instance-spec projection (procedural environments)
# ---------------------------------------------------------------------------

def parse_instance_spec(text: str) -> dict[str, Any]:
    """Read the baked ``INSTANCE_SPEC`` literal without executing env code."""
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "INSTANCE_SPEC"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                raise ValueError("INSTANCE_SPEC must be a mapping literal")
            return value
    raise ValueError("judge/instance_spec.py does not assign INSTANCE_SPEC")


def project_instance_spec(spec: Mapping[str, Any], identity_keys: Sequence[str]) -> dict[str, Any]:
    """Select the declared identity projection of a baked instance spec.

    A key missing from the spec is an error, not a skip: a projection that silently
    dropped a key would merge instances the declaration says are different.  Dotted
    keys select one nested field from each entry of a mapping
    (``hypotheses.level`` -> ``{world: {..., level: ...}}`` reduced to the field).
    """
    projection: dict[str, Any] = {}
    for key in identity_keys:
        head, dot, sub = str(key).partition(".")
        if head not in spec:
            raise ValueError(f"identity_key {key!r}: {head!r} is not in the instance spec")
        value = spec[head]
        if dot:
            if not isinstance(value, Mapping):
                raise ValueError(f"identity_key {key!r}: {head!r} is not a mapping")
            value = {
                str(item_key): (item.get(sub) if isinstance(item, Mapping) else None)
                for item_key, item in value.items()
            }
        projection[str(key)] = value
    return projection


# ---------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------

def _evaluator_state(
    config: Mapping[str, Any],
    fdecl: Mapping[str, Any],
    subs: Mapping[str, str],
) -> dict[str, Any]:
    """How this instance is measured: scoring rule, judge-side allowlists, judge set.

    Recorded from structure, not bytes: a judge *content* hash would move under a
    declared renaming (the judge legitimately imports the renamed module), which
    would split presentation twins - the collision evaluator_state exists to
    prevent is between different measurements, not between different names.
    """
    state: dict[str, Any] = {}
    if fdecl.get("scoring", True):
        state["scoring"] = dict(config.get("scoring") or {})
    if fdecl.get("constants", True):
        state["constants"] = {
            gm.strip_placeholders(str(key)): str(subs.get(gm.strip_placeholders(str(key)), ""))
            for key in (config.get("constants") or {})
        }
    if fdecl.get("judge_files", True):
        state["judge_files"] = sorted(
            str(target) for target in (config.get("layout") or {}) if str(target).startswith("judge/")
        )
    for raw in fdecl.get("placeholders") or []:
        name = gm.strip_placeholders(str(raw))
        state[name] = str(subs.get(name, ""))
    return state


def derive_spec(
    *,
    env_name: str,
    seed: int,
    config: Mapping[str, Any],
    subs: Mapping[str, str],
    identity_rewrites: Iterable[tuple[str, str]] = (),
    instance_spec_text: str | None = None,
    information_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the latent spec document for one generated instance.

    ``identity_rewrites`` are (twin, base) value pairs from every applied
    ``semantically_equivalent`` overlay; they canonicalize identity values so a
    presentation twin hashes to the same task.  Raw factor values are *not*
    canonicalized: the spec records the instance as generated, and the tree-level
    normalization in ``twin_check`` is what proves the twin relation on bytes.

    ``information_policy`` (item 5) is the generation-time record of a declared
    evidence-selection policy: its repo-relative source path, the sha256 of the
    module that shipped to the judge, and the placeholder selection it returned.
    It is recorded top-level, outside the identity payload: a constant policy id
    enters identity only where a factor declares it (epistemic
    causal_mechanism carries POLICY_ID).
    """
    block = dict(config.get("latent_factors") or {})
    factors_decl = dict(block.get("factors") or {})
    rewrites = compile_identity_rewrites(identity_rewrites)

    factors_out: dict[str, Any] = {}
    identity_factors: dict[str, Any] = {}
    for fname in FACTORS:
        fdecl = factors_decl.get(fname)
        if fdecl is None:
            factors_out[fname] = {UNAVAILABLE: "not declared for this environment"}
            if fname in IDENTITY_FACTORS:
                identity_factors[fname] = UNAVAILABLE
            continue
        if UNAVAILABLE in fdecl:
            factors_out[fname] = {UNAVAILABLE: str(fdecl[UNAVAILABLE])}
            if fname in IDENTITY_FACTORS:
                identity_factors[fname] = UNAVAILABLE
            continue

        if fname == "evaluator_state":
            value: Any = _evaluator_state(config, fdecl, subs)
        else:
            value = {}
            source = str(fdecl.get("source") or "substitutions")
            if source == "instance_spec":
                if instance_spec_text is None:
                    raise ValueError(
                        f"{env_name}: latent_factors.{fname} declares source "
                        "'instance_spec' but this generation baked no "
                        "judge/instance_spec.py"
                    )
                baked = parse_instance_spec(instance_spec_text)
                identity_keys = list(fdecl.get("identity_keys") or [])
                if identity_keys:
                    value["instance_spec"] = project_instance_spec(baked, identity_keys)
                else:
                    # No declared projection: the whole baked spec is the claim.
                    value["instance_spec"] = baked
            for raw in fdecl.get("placeholders") or []:
                name = gm.strip_placeholders(str(raw))
                value[name] = str(subs.get(name, ""))
        # The spec records the instance as generated (raw values); only the identity
        # digest is canonicalized through declared presentation renamings.
        factors_out[fname] = value

        if fname in IDENTITY_FACTORS:
            identity_factors[fname] = gm.sha256_text(
                canonical_json(canonicalize(value, rewrites))
            )

    identity = {
        "schema": IDENTITY_SCHEMA,
        "environment": str(env_name),
        "seed": int(seed),
        "factors": {fname: identity_factors.get(fname, UNAVAILABLE) for fname in IDENTITY_FACTORS},
    }
    identity_sha = gm.sha256_text(canonical_json(identity))

    declared_by = str(block.get("declared_by") or "")
    notes = [
        "identity enters pair_id; observable_state and proxy_signal are recorded but "
        "never split a pair (an observation twin is the same task under different evidence)",
    ]
    if declared_by == "scaffold_unreviewed":
        notes.append(
            "declared_by: scaffold_unreviewed - the factor mapping was produced "
            "mechanically by tools/latent_factors_scaffold.py and is not a reviewed "
            "causal claim"
        )
    mechanism = factors_decl.get("causal_mechanism")
    if isinstance(mechanism, Mapping) and UNAVAILABLE in mechanism:
        notes.append(
            "the derived spec records which placeholders were instantiated; for a "
            "template environment that is not a causal model (item 4 honesty constraint)"
        )
    policy_section: dict[str, Any] | None = None
    if information_policy:
        policy_section = json.loads(canonical_json(dict(information_policy)))
        notes.append(
            "information_policy: the evidence-selection declaration for this "
            "instance (item 5); the module ships to the judge and is re-run "
            "there against the rebuilt spec - a replay mismatch is reward_denial, "
            "because prompt prose about how evidence was selected is not graded"
        )
    return {
        "schema_version": SPEC_SCHEMA_VERSION,
        "spec_type": SPEC_TYPE,
        "environment": str(env_name),
        "seed": int(seed),
        "declared_by": declared_by,
        "identity": {"payload": identity, "sha256": identity_sha},
        "factors": factors_out,
        "information_policy": policy_section,
        "latent_factors": json.loads(canonical_json(dict(block))),
        "notes": notes,
    }


def write_spec(directory: Path | str, spec: Mapping[str, Any]) -> Path:
    target = Path(directory) / SPEC_NAME
    text = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    gm._atomic_write_text(target, text)
    return target


def read_spec(directory: Path | str) -> dict[str, Any]:
    path = Path(directory) / SPEC_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {SPEC_NAME} in {directory}")
    return json.loads(path.read_text(encoding="utf-8"))


def recompute_identity_sha256(spec: Mapping[str, Any]) -> str:
    """Recompute the identity hash from a spec document's own payload."""
    payload = (spec.get("identity") or {}).get("payload")
    if payload is None:
        raise ValueError(f"{SPEC_NAME}: no identity payload to recompute")
    return gm.sha256_text(canonical_json(payload))
