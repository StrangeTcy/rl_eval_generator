#!/usr/bin/env python3
"""Staged frontier-model study for the recursive local-to-global family.

One manual dispatch, two scopes, one reporting contract:

* ``diagnostic`` - the two primary conditions only, on a small curated matrix:
  ``recursive_gluing`` (the expanded control: an explicit region/overlap network)
  and ``recursive_gluing_discovery`` (the compact recursively defined grammar).
  The matrix is curated rather than one-axis-at-a-time because the hypothesis is
  about interactions: an opaque cyclic obstruction, a decoy leaf under an
  unsatisfiable closing, and the maximum intended depth must appear *together*
  for a copy-the-local-table-upward strategy to be distinguishable from a
  reconstruction of the composition rule.
* ``family`` - the same contract extended to every registered member of the
  recursive local-to-global family, with a strength-2 pairwise design by default
  (or ``covering`` / ``representative`` on explicit request).

This module is the thin profile the repository's manifest-driven suite was
missing.  It does not run a model itself and it does not duplicate the
controller: ``plan`` builds a deterministic, *filtered* manifest and a
provider-free budget plan, and ``run`` forwards to :func:`tools.run_suite.run_suite`
with the operator's explicit ceilings.  ``report`` turns the controller's
checkpoint into machine-readable JSON/CSV plus a readable summary, keeping every
environment, diagnostic factor and hidden check separate.

Fail-closed rules (all provider-free):

* the registered family must match :data:`FAMILY` exactly - a new or removed
  member is an operator decision, not something this profile may absorb;
* an empty selection, a duplicate case id, an unknown scope or matrix, or a
  manifest that would retain an unrelated registry environment is an error;
* a plan that does not fit inside the declared ceilings is an error, not a
  warning;
* environments without a behavioural reference (the exact-instance gate cannot
  certify them) are excluded from live scored evaluation by default and named
  with a reason.  There is no compile-only path in this profile.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import recursive_references  # noqa: E402
from tools.suite_inventory import (  # noqa: E402
    _case_id,
    _difficulty_vectors,
    _load_registry,
    _load_yaml,
    _sha256,
    _track_for_path,
    _validate_axes,
)

PROFILE_NAME = "recursive-gluing-frontier"
PROFILE_VERSION = "1"

# The complete recursive local-to-global family, in registry order.  This is a
# pinned expectation: ``verify_family`` fails closed if the registry disagrees,
# so a member can never be silently dropped from, or added to, a study run.
FAMILY: tuple[str, ...] = (
    "recursive_gluing",
    "recursive_gluing_discovery",
    "recursive_maze_gluing",
    "recursive_distributed_gluing",
    "recursive_epistemic_gluing",
    "recursive_holonomy_gluing",
    "recursive_compiler_bootstrap",
    "recursive_error_correcting_codes",
    "recursive_coarse_graining",
)
PRIMARY: tuple[str, ...] = ("recursive_gluing", "recursive_gluing_discovery")

# Explicitly labelled experimental conditions.  They are never pooled into one
# score; see ``build_report``.
CONDITIONS: dict[str, str] = {
    "recursive_gluing": "expanded_control",
    "recursive_gluing_discovery": "recursive_discovery",
}

SCOPES: tuple[str, ...] = ("diagnostic", "family")
MATRICES_BY_SCOPE: dict[str, tuple[str, ...]] = {
    "diagnostic": ("diagnostic",),
    "family": ("diagnostic", "pairwise", "covering", "representative"),
}
EXECUTION_MODES: tuple[str, ...] = ("plan_only", "gates_only", "live")
PROVIDERS: tuple[str, ...] = (
    "agentrouter",
    "atria",
    "mercury",
    "groq",
    "nvidia",
    "gemini",
    "openrouter",
    "cloudflare",
    "custom",
    "huggingface",
)

# Per-episode bounds are the controller's (``tools/run_suite.py``), not a second
# budget language.  These are only defaults for the diagnostic dispatch.
DEFAULT_MAX_STEPS = 24
DEFAULT_MAX_TOKENS = 4096
DEFAULT_INVALID_RETRIES = 2
ESTIMATED_SECONDS_PER_CASE = 600
MINIMUM_SECONDS_PER_CASE = 120
GATE_RESERVE_SECONDS = 3600
MAX_FAMILY_CASES = 400
# A hosted Actions job is capped at six hours; the controller must stop well
# before that so its checkpoint and artifacts are uploaded rather than deleted
# with the worker.  This is a hard plan ceiling, not a provider limit.
MAX_DISPATCH_WALL_SECONDS = 21_000

# Which hidden check decides the satisfiability question in each environment.
# A scored failure that flips this check is a wrong *decision*, which is not the
# same finding as a wrong certificate or a malformed answer.
# Axes that a family design must pin to a certified level.  These are not
# preference: the value is the only one whose *public* instance is enough to
# replay the judge's reference certificate, which is what the exact-instance gate
# re-derives.  Pinning is recorded on every case and in the plan so a reader can
# see that this axis was not varied for that environment.
_INFERRED_REPRESENTATION_REASON = (
    "representation=inferred hides the root structure (maps / encodings / decoder / perms) from "
    "the public instance, so the judge's own reference certificate cannot be replayed from what "
    "the episode receives and no behavioural reference exists for that column; only "
    "representation=revealed is gate-certifiable"
)

AXIS_PINS: dict[str, dict[str, tuple[str, str]]] = {
    name: {"representation": ("easy", _INFERRED_REPRESENTATION_REASON)}
    for name in (
        "recursive_coarse_graining",
        "recursive_holonomy_gluing",
        "recursive_compiler_bootstrap",
        "recursive_error_correcting_codes",
    )
}

DECISION_CHECKS: dict[str, tuple[str, ...]] = {
    "recursive_gluing": ("obstructed_cycle", "cyclic_unsat_generated"),
    "recursive_gluing_discovery": ("assembled_unsat", "configured"),
    "recursive_maze_gluing": ("assembled_unsat",),
    "recursive_distributed_gluing": ("assembled_unsat",),
    "recursive_epistemic_gluing": ("assembled_unsat",),
    "recursive_coarse_graining": ("assembled_unsat",),
}

# Outcomes.  A timeout, a missing row or a failed gate is never a model score and
# never evidence for unsatisfiability.
OUTCOME_VALIDATED_SUCCESS = "validated_success"
OUTCOME_SCORED_FAILURE = "scored_model_failure"
OUTCOME_MALFORMED = "malformed_or_incomplete_certificate"
OUTCOME_WRONG_DECISION = "incorrect_satisfiability_decision"
OUTCOME_PROVIDER = "provider_failure"
OUTCOME_INFRASTRUCTURE = "infrastructure_failure"
OUTCOME_ORACLE = "oracle_or_gate_failure"
OUTCOME_TIMEOUT = "timeout_or_resource_budget_exhaustion"
OUTCOME_MISSING = "missing_result"
OUTCOME_COMPILE_ONLY = "compile_only_unvalidated"

OUTCOMES: tuple[str, ...] = (
    OUTCOME_VALIDATED_SUCCESS,
    OUTCOME_SCORED_FAILURE,
    OUTCOME_MALFORMED,
    OUTCOME_WRONG_DECISION,
    OUTCOME_PROVIDER,
    OUTCOME_INFRASTRUCTURE,
    OUTCOME_ORACLE,
    OUTCOME_TIMEOUT,
    OUTCOME_MISSING,
    OUTCOME_COMPILE_ONLY,
)


class StudyError(RuntimeError):
    """A fail-closed planning, launch, or reporting error."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Registry, family and axis handling
# ---------------------------------------------------------------------------


def recursive_family(registry: Mapping[str, str]) -> list[str]:
    """Registered environment names that belong to the recursive family."""

    return [name for name in registry if name.startswith("recursive_")]


def verify_family(registry: Mapping[str, str]) -> None:
    """Fail closed unless the registry still carries exactly :data:`FAMILY`."""

    registered = recursive_family(registry)
    missing = [name for name in FAMILY if name not in registered]
    unexpected = [name for name in registered if name not in FAMILY]
    if missing or unexpected:
        raise StudyError(
            "the registered recursive local-to-global family changed; "
            f"missing={missing or 'none'} unexpected={unexpected or 'none'}. "
            "Update tools/recursive_gluing_study.py FAMILY deliberately (and the "
            "workflow/report tests) instead of letting a dispatch absorb the change."
        )


def _config_for(root: Path, registry: Mapping[str, str], environment: str) -> dict[str, Any]:
    relative = registry.get(environment)
    if not relative:
        raise StudyError(f"{environment}: not in envs/registry.yaml")
    path = root / relative
    if not path.is_file():
        raise StudyError(f"{environment}: registered config is missing: {relative}")
    return _load_yaml(path)


def _levels(config: Mapping[str, Any], axis_id: str) -> list[str]:
    for axis in config.get("axes", []) or []:
        if isinstance(axis, dict) and axis.get("id") == axis_id:
            levels = axis.get("levels")
            if not isinstance(levels, dict) or not levels:
                raise StudyError(f"axis {axis_id!r} has no levels")
            return list(levels)
    raise StudyError(f"axis {axis_id!r} is not configured")


def _difficulty_string(config: Mapping[str, Any], levels: Mapping[str, str]) -> str:
    axes = [axis for axis in config.get("axes", []) or [] if isinstance(axis, dict)]
    values = []
    for axis in axes:
        axis_id = axis["id"]
        if axis_id not in levels:
            raise StudyError(f"case does not choose axis {axis_id!r}")
        if levels[axis_id] not in (axis.get("levels") or {}):
            raise StudyError(f"axis {axis_id!r} has no level {levels[axis_id]!r}")
        values.append(str(levels[axis_id]))
    extra = sorted(set(levels) - {axis["id"] for axis in axes})
    if extra:
        raise StudyError(f"case chooses unknown axes: {extra}")
    return ",".join(values)


def _environment_record(root: Path, registry: Mapping[str, str], environment: str) -> dict[str, Any]:
    relative = registry[environment]
    path = root / relative
    config = _config_for(root, registry, environment)
    axes, issues = _validate_axes(config, path)
    return {
        "environment": environment,
        "registry_names": [name for name, value in registry.items() if value == relative],
        "config_path": Path(relative).as_posix(),
        "config_sha256": _sha256(path),
        "track": _track_for_path(path),
        "axes": axes,
        "axis_count": len(axes),
        "difficulty_vector_count": 0,
        "issues": issues,
    }


def _pin_levels(environment: str, levels: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Apply :data:`AXIS_PINS` and report which axes were pinned."""

    pinned = dict(levels)
    applied: dict[str, str] = {}
    for axis_id, (level, _reason) in AXIS_PINS.get(environment, {}).items():
        if axis_id not in pinned:
            raise StudyError(f"{environment}: axis pin names unknown axis {axis_id!r}")
        if pinned[axis_id] != level:
            applied[axis_id] = level
        pinned[axis_id] = level
    return pinned, applied


def _make_case(
    root: Path,
    registry: Mapping[str, str],
    environment: str,
    levels: Mapping[str, str],
    seed: int,
    *,
    factor: str,
    rationale: str,
    expectation: str,
) -> dict[str, Any]:
    config = _config_for(root, registry, environment)
    levels, pinned_applied = _pin_levels(environment, levels)
    difficulty = _difficulty_string(config, levels)
    record = _environment_record(root, registry, environment)
    case = {
        "case_id": _case_id(environment, dict(levels), int(seed)),
        "environment": environment,
        "condition": CONDITIONS.get(environment, "family_member"),
        "config_path": record["config_path"],
        "config_sha256": record["config_sha256"],
        "track": record["track"],
        "runner": "arena_episode",
        "difficulty_levels": dict(levels),
        "difficulty": difficulty,
        "seed": int(seed),
        "status": "planned",
        "study": {
            "profile": f"{PROFILE_NAME}/{PROFILE_VERSION}",
            "factor": factor,
            "rationale": rationale,
            "expectation": expectation,
            "pinned_levels": pinned_applied,
        },
    }
    return case


# ---------------------------------------------------------------------------
# Curated diagnostic matrix
# ---------------------------------------------------------------------------

# (factor, environment, {axis: level}, seed, rationale, expectation)
#
# The control's axes are recursive_depth, state_space, gluing_regime,
# label_opacity; the discovery condition replaces state_space with the interface
# alphabet and adds structural_ambiguity.  A factor name is the unit the report
# aggregates by, so combined conditions get their own name instead of being
# averaged into a single-axis main effect.
DIAGNOSTIC_SPECS: tuple[tuple[str, str, dict[str, str], int, str, str], ...] = (
    (
        "baseline_tree_sat",
        "recursive_gluing",
        {"recursive_depth": "easy", "state_space": "easy", "gluing_regime": "easy", "label_opacity": "easy"},
        0,
        "Straightforward acyclic satisfiable baseline with readable labels.",
        "sat with a globally consistent assignment",
    ),
    (
        "cyclic_sat",
        "recursive_gluing",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "medium", "label_opacity": "easy"},
        0,
        "Satisfiable network whose overlaps form a cycle.",
        "sat",
    ),
    (
        "cyclic_unsat_locally_nonempty",
        "recursive_gluing",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "hard", "label_opacity": "easy"},
        0,
        "Cyclic global obstruction while every domain and overlap table stays nonempty.",
        "unsat, and the local tables give no shortcut",
    ),
    (
        "opaque_labels",
        "recursive_gluing",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "medium", "label_opacity": "hard"},
        0,
        "Same satisfiable cycle under per-region opaque labelling.",
        "sat; the answer is presentation invariant",
    ),
    (
        "opacity_x_unsat",
        "recursive_gluing",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "hard", "label_opacity": "hard"},
        0,
        "Interaction: the obstruction must still be found when labels cannot be read across regions.",
        "unsat",
    ),
    (
        "nested_tree_opaque",
        "recursive_gluing",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "easy", "label_opacity": "hard"},
        0,
        "Nested structure without a cycle: depth is exercised separately from the obstruction.",
        "sat",
    ),
    (
        "max_depth_unsat",
        "recursive_gluing",
        {"recursive_depth": "hard", "state_space": "hard", "gluing_regime": "hard", "label_opacity": "hard"},
        0,
        "Maximum intended depth and domain under the obstruction, opaque labels.",
        "unsat",
    ),
    (
        "max_depth_unsat_stability_seed",
        "recursive_gluing",
        {"recursive_depth": "hard", "state_space": "hard", "gluing_regime": "hard", "label_opacity": "hard"},
        1,
        "The same maximum-depth condition on a held-out seed: is the behaviour stable or seed luck?",
        "unsat",
    ),
    (
        "baseline_tree_sat",
        "recursive_gluing_discovery",
        {"recursive_depth": "easy", "state_space": "easy", "gluing_regime": "easy", "label_opacity": "easy", "structural_ambiguity": "easy"},
        0,
        "Compact grammar, depth 3, no closing relation, readable ports.",
        "sat with the complete realizable summary",
    ),
    (
        "cyclic_sat",
        "recursive_gluing_discovery",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "medium", "label_opacity": "easy", "structural_ambiguity": "easy"},
        0,
        "Identity closing met by the composed interface relation.",
        "sat",
    ),
    (
        "cyclic_unsat_locally_nonempty",
        "recursive_gluing_discovery",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "hard", "label_opacity": "easy", "structural_ambiguity": "easy"},
        0,
        "Closing cannot be met although every leaf table and every transport is nonempty.",
        "unsat",
    ),
    (
        "opaque_labels",
        "recursive_gluing_discovery",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "medium", "label_opacity": "hard", "structural_ambiguity": "easy"},
        0,
        "Per-type opaque port labels on a satisfiable grammar.",
        "sat; transport must be read through the tables, not the names",
    ),
    (
        "decoy_leaf",
        "recursive_gluing_discovery",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "medium", "label_opacity": "easy", "structural_ambiguity": "hard"},
        0,
        "A second depth-1 leaf type with a different pair table.",
        "sat; treating the decoy as the tip changes the summary",
    ),
    (
        "copy_upward_foil",
        "recursive_gluing_discovery",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "hard", "label_opacity": "easy", "structural_ambiguity": "hard"},
        0,
        "Obstruction plus decoy: copying a leaf table upward yields a confident, wrong 'sat'.",
        "unsat",
    ),
    (
        "opacity_x_unsat",
        "recursive_gluing_discovery",
        {"recursive_depth": "medium", "state_space": "medium", "gluing_regime": "hard", "label_opacity": "hard", "structural_ambiguity": "easy"},
        0,
        "Interaction: obstruction under opaque per-type labels.",
        "unsat",
    ),
    (
        "max_depth_unsat",
        "recursive_gluing_discovery",
        {"recursive_depth": "hard", "state_space": "hard", "gluing_regime": "hard", "label_opacity": "hard", "structural_ambiguity": "hard"},
        0,
        "Maximum intended depth (unfolds far past any materialised tree), obstruction, opaque labels, decoy leaf.",
        "unsat with the complete depth-indexed summary",
    ),
    (
        "max_depth_sat",
        "recursive_gluing_discovery",
        {"recursive_depth": "hard", "state_space": "medium", "gluing_regime": "medium", "label_opacity": "hard", "structural_ambiguity": "easy"},
        0,
        "Maximum intended depth, satisfiable closing: separates depth from unsatisfiability.",
        "sat",
    ),
    (
        "max_depth_unsat_stability_seed",
        "recursive_gluing_discovery",
        {"recursive_depth": "hard", "state_space": "hard", "gluing_regime": "hard", "label_opacity": "hard", "structural_ambiguity": "hard"},
        1,
        "The maximum-depth condition on a held-out seed.",
        "unsat",
    ),
)


def diagnostic_cases(
    root: Path = ROOT,
    *,
    seeds: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """The curated diagnostic matrix, optionally restricted to chosen seeds.

    ``seeds`` selects which of the *fixed* seed values are kept; it never
    replaces a curated case with another one.  A seed that the matrix does not
    use is reported as an error rather than silently ignored.
    """

    registry = _load_registry(root)
    verify_family(registry)
    wanted = list(seeds) if seeds is not None else None
    available = sorted({spec[3] for spec in DIAGNOSTIC_SPECS})
    if wanted is not None:
        unknown = [seed for seed in wanted if seed not in available]
        if unknown:
            raise StudyError(
                f"diagnostic matrix fixes seeds {available}; requested {unknown} have no curated case. "
                "Change DIAGNOSTIC_SPECS deliberately instead of remapping a seed."
            )
    cases = []
    for factor, environment, levels, seed, rationale, expectation in DIAGNOSTIC_SPECS:
        if wanted is not None and seed not in wanted:
            continue
        cases.append(
            _make_case(
                root,
                registry,
                environment,
                levels,
                seed,
                factor=factor,
                rationale=rationale,
                expectation=expectation,
            )
        )
    return cases


# ---------------------------------------------------------------------------
# Family matrix
# ---------------------------------------------------------------------------


def _family_matrix_vectors(root: Path, registry: Mapping[str, str], matrix: str) -> dict[str, list[dict[str, str]]]:
    if matrix not in MATRICES_BY_SCOPE["family"]:
        raise StudyError(f"unknown family matrix {matrix!r}")
    vectors: dict[str, list[dict[str, str]]] = {}
    for environment in FAMILY:
        config = _config_for(root, registry, environment)
        axes, issues = _validate_axes(config, root / registry[environment])
        if issues:
            raise StudyError(f"{environment}: " + "; ".join(issues))
        if matrix == "diagnostic":
            continue
        vectors[environment] = _difficulty_vectors(axes, matrix, None)
    return vectors


def family_cases(
    root: Path = ROOT,
    *,
    matrix: str = "pairwise",
    seeds: Sequence[int] = (0,),
) -> list[dict[str, Any]]:
    if matrix == "diagnostic":
        # The family run can still use the curated matrix, but over every family
        # member: a shared profile of baseline / obstruction / maximum-depth
        # conditions, which keeps a cross-domain comparison readable.
        return _family_curated_cases(root, seeds=seeds)
    registry = _load_registry(root)
    verify_family(registry)
    vectors = _family_matrix_vectors(root, registry, matrix)
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for environment in FAMILY:
        config = _config_for(root, registry, environment)
        axes = [axis for axis in config.get("axes", []) or [] if isinstance(axis, dict)]
        for vector in vectors[environment]:
            for seed in seeds:
                factor = matrix
                descriptor = ", ".join(f"{axis['id']}={vector[axis['id']]}" for axis in axes)
                candidate = (
                    _make_case(
                        root,
                        registry,
                        environment,
                        vector,
                        int(seed),
                        factor=factor,
                        rationale=f"strength-2 {matrix} design vector: {descriptor}",
                        expectation="mixed; the design exists to expose axis interactions",
                    )
                )
                # A pinned axis can collapse two design vectors onto one case;
                # keep one and let the plan count what is actually run.
                if candidate["case_id"] in seen:
                    continue
                seen.add(candidate["case_id"])
                cases.append(candidate)
    return cases


def _family_curated_cases(root: Path, *, seeds: Sequence[int]) -> list[dict[str, Any]]:
    """Three pinned conditions per family member, at its own axis names.

    ``baseline`` is the first level of every axis, ``obstruction`` is the hardest
    level of the gluing/regime axis with the rest left at their first level, and
    ``maximum`` is the hardest level of every axis.
    """

    registry = _load_registry(root)
    verify_family(registry)
    cases: list[dict[str, Any]] = []
    for environment in FAMILY:
        config = _config_for(root, registry, environment)
        axes = [axis for axis in config.get("axes", []) or [] if isinstance(axis, dict)]
        if not axes:
            raise StudyError(f"{environment}: no axes")
        baseline = {axis["id"]: list(axis["levels"])[0] for axis in axes}
        maximum = {axis["id"]: list(axis["levels"])[-1] for axis in axes}
        regime_axis = next(
            (
                axis
                for axis in axes
                if "regime" in axis["id"] or "family" in axis["id"]
            ),
            None,
        )
        obstruction = dict(baseline)
        if regime_axis is not None:
            obstruction[regime_axis["id"]] = list(regime_axis["levels"])[-1]
        seen_here: set[str] = set()
        for factor, levels in (
            ("family_baseline", baseline),
            ("family_obstruction", obstruction),
            ("family_maximum", maximum),
        ):
            for seed in seeds:
                candidate = _make_case(
                        root,
                        registry,
                        environment,
                        levels,
                        int(seed),
                        factor=factor,
                        rationale=f"{factor} for {environment}",
                        expectation="mixed",
                    )
                if candidate["case_id"] in seen_here:
                    continue
                seen_here.add(candidate["case_id"])
                cases.append(candidate)
    return cases


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def case_budget(max_steps: int, max_tokens: int, invalid_retries: int) -> tuple[int, int]:
    """Per-case worst-case (api calls, output tokens).

    Mirrors ``tools.run_suite._estimated_case_budget`` so the plan cannot drift
    from the controller's own arithmetic; importing that private helper would
    make two call sites responsible for keeping the profile honest.
    """

    if max_steps < 1 or max_tokens < 1 or invalid_retries < 0:
        raise StudyError("max_steps and max_tokens must be positive; invalid_retries must not be negative")
    calls = max_steps * (1 + invalid_retries)
    return calls, calls * max_tokens


def build_plan(
    cases: Sequence[Mapping[str, Any]],
    *,
    scope: str,
    matrix: str,
    seeds: Sequence[int],
    provider: str,
    model: str,
    api_base: str | None,
    wire_api: str,
    reasoning_effort: str | None,
    max_api_calls: int,
    max_tokens_total: int,
    max_wall_seconds: float,
    max_steps: int,
    max_tokens: int,
    invalid_retries: int = DEFAULT_INVALID_RETRIES,
    excluded: Sequence[Mapping[str, Any]] = (),
    shard: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Provider-free plan: case count, selection, and worst-case budget."""

    if not cases:
        raise StudyError("empty selection: refusing to plan a run with no cases")
    case_ids = [str(case["case_id"]) for case in cases]
    duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    if duplicates:
        raise StudyError(f"duplicate case ids in the selection: {duplicates}")
    if scope not in SCOPES:
        raise StudyError(f"unknown scope {scope!r}; choose from {', '.join(SCOPES)}")
    if matrix not in MATRICES_BY_SCOPE[scope]:
        raise StudyError(
            f"matrix {matrix!r} is not offered for scope {scope!r}; "
            f"choose from {', '.join(MATRICES_BY_SCOPE[scope])}"
        )
    if scope == "family" and len(cases) > MAX_FAMILY_CASES:
        raise StudyError(
            f"family selection has {len(cases)} cases, above the profile ceiling of {MAX_FAMILY_CASES}; "
            "narrow the matrix or the seeds deliberately"
        )
    if provider not in PROVIDERS:
        raise StudyError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
    if not model or model != model.strip():
        raise StudyError("a single exact model id is required (no whitespace, no catalogue lookup)")
    if wire_api not in {"chat_completions", "responses"}:
        raise StudyError("wire_api must be 'chat_completions' or 'responses'")
    if provider == "agentrouter" and wire_api != "chat_completions":
        raise StudyError("AgentRouter is configured for the OpenAI-compatible chat_completions API")
    if reasoning_effort is not None:
        if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise StudyError(f"unsupported reasoning_effort {reasoning_effort!r}")
        if (provider, wire_api) not in {("mercury", "chat_completions"), ("atria", "responses")}:
            raise StudyError(
                "controlled reasoning is defined in this repository only for Mercury Chat "
                "Completions and Atria Responses; refusing to invent a provider equivalent"
            )
    if api_base:
        from arena.providers import require_https

        try:
            require_https(api_base)
        except ValueError as exc:
            raise StudyError(f"api_base must be an absolute HTTPS URL: {exc}") from exc

    calls, tokens = case_budget(max_steps, max_tokens, invalid_retries)
    worst_calls = calls * len(cases)
    worst_tokens = tokens * len(cases)
    minimum_wall = MINIMUM_SECONDS_PER_CASE * len(cases) + (GATE_RESERVE_SECONDS if scope == "family" else 0)
    estimated_wall = ESTIMATED_SECONDS_PER_CASE * len(cases) + GATE_RESERVE_SECONDS
    checks = [
        {
            "name": "cases_present",
            "ok": bool(cases),
            "detail": f"{len(cases)} planned cases",
        },
        {
            "name": "max_api_calls",
            "ok": max_api_calls >= worst_calls,
            "detail": f"ceiling {max_api_calls} vs worst case {worst_calls}",
        },
        {
            "name": "max_tokens_total",
            "ok": max_tokens_total >= worst_tokens,
            "detail": f"ceiling {max_tokens_total} vs worst case {worst_tokens}",
        },
        {
            "name": "max_wall_seconds",
            "ok": max_wall_seconds >= minimum_wall,
            "detail": (
                f"ceiling {int(max_wall_seconds)}s vs minimum {int(minimum_wall)}s "
                f"(estimate {int(estimated_wall)}s)"
            ),
        },
        {
            "name": "no_compile_only",
            "ok": True,
            "detail": "every selected environment has a behavioural reference",
        },
        {
            "name": "dispatch_wall_cap",
            "ok": max_wall_seconds <= MAX_DISPATCH_WALL_SECONDS,
            "detail": (
                f"ceiling {int(max_wall_seconds)}s must stay under {MAX_DISPATCH_WALL_SECONDS}s "
                "so a hosted runner uploads its checkpoint instead of being killed"
            ),
        },
    ]
    warnings = []
    if estimated_wall > max_wall_seconds:
        warnings.append(
            f"the {int(estimated_wall)}s estimate ({len(cases)} cases at {ESTIMATED_SECONDS_PER_CASE}s) "
            f"exceeds the declared {int(max_wall_seconds)}s wall ceiling: the controller will pause "
            "mid-run and report unrecorded cases as missing_result. Raise the ceiling (at most "
            f"{MAX_DISPATCH_WALL_SECONDS}s) or dispatch the same seeds/model with --shard-count N and one "
            "--shard-index per dispatch."
        )
    plan = {
        "profile": {"name": PROFILE_NAME, "version": PROFILE_VERSION},
        "provider_free": True,
        "scope": scope,
        "matrix": matrix,
        "seeds": list(seeds),
        "provider": provider,
        "model": model,
        "api_base": api_base or None,
        "wire_api": wire_api,
        "reasoning_effort": reasoning_effort,
        "case_count": len(cases),
        "case_ids": case_ids,
        "environments": sorted({str(case["environment"]) for case in cases}),
        "factors": sorted({str(case.get("study", {}).get("factor")) for case in cases}),
        "excluded_environments": list(excluded),
        "shard": dict(shard or {"index": 0, "count": 1}),
        "per_case_limits": {
            "max_steps": max_steps,
            "max_tokens": max_tokens,
            "invalid_retries": invalid_retries,
            "worst_case_api_calls": calls,
            "worst_case_output_tokens": tokens,
        },
        "limits": {
            "max_api_calls": max_api_calls,
            "max_tokens_total": max_tokens_total,
            "max_wall_seconds": max_wall_seconds,
        },
        "worst_case": {
            "api_calls": worst_calls,
            "output_tokens": worst_tokens,
            "estimated_wall_seconds": estimated_wall,
            "minimum_wall_seconds": minimum_wall,
        },
        "within_limits": all(check["ok"] for check in checks),
        "checks": checks,
        "warnings": warnings,
    }
    failed = [check for check in checks if not check["ok"]]
    if failed:
        raise StudyError(
            "the plan does not fit the declared ceilings: "
            + "; ".join(f"{check['name']} ({check['detail']})" for check in failed)
        )
    return plan


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _gated_environments() -> set[str]:
    return set(recursive_references.reference_environments())


def _exclude_ungated(
    cases: Sequence[Mapping[str, Any]],
    *,
    execution_mode: str,
    scope: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop environments the exact-instance gate cannot certify.

    Planning still reports them (and their reason) so the operator sees what the
    family run does not cover.  A live run of the two primaries is refused
    outright if either lost its reference: silently running a weaker guarantee
    is exactly what the gate exists to prevent.
    """

    gated = _gated_environments()
    kept = [dict(case) for case in cases if str(case["environment"]) in gated]
    dropped: dict[str, dict[str, Any]] = {}
    for case in cases:
        environment = str(case["environment"])
        if environment in gated:
            continue
        dropped.setdefault(
            environment,
            {
                "environment": environment,
                "reason": "no_behavioural_reference",
                "detail": (
                    "the exact-instance gate has no correct/incorrect reference pair for this "
                    "environment (it hides a representation the judge oracle needs at "
                    "representation=inferred), so a scored live result cannot be certified; "
                    "the case is excluded rather than run under compile-only judging"
                ),
                "dropped_case_count": 0,
            },
        )
        dropped[environment]["dropped_case_count"] += 1
    if execution_mode == "live" and scope == "diagnostic":
        lost = sorted({str(case["environment"]) for case in cases} - gated)
        if lost:
            raise StudyError(
                "a diagnostic environment has no behavioural reference, so the live scope "
                f"cannot be certified: {lost}. Run plan_only, or restore the reference."
            )
    return kept, [dropped[name] for name in sorted(dropped)]


def build_study_manifest(
    *,
    scope: str = "diagnostic",
    matrix: str | None = None,
    seeds: Sequence[int] | None = None,
    execution_mode: str = "plan_only",
    provider: str = "agentrouter",
    model: str = "PLACEHOLDER-SET-ME",
    api_base: str | None = None,
    wire_api: str = "chat_completions",
    reasoning_effort: str | None = None,
    max_api_calls: int = 2000,
    max_tokens_total: int = 8_000_000,
    max_wall_seconds: float = 14_400,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    invalid_retries: int = DEFAULT_INVALID_RETRIES,
    shard_index: int = 0,
    shard_count: int = 1,
    root: Path = ROOT,
    created_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(manifest, plan)`` for one dispatch configuration."""

    root = root.resolve()
    if scope not in SCOPES:
        raise StudyError(f"unknown scope {scope!r}; choose from {', '.join(SCOPES)}")
    if execution_mode not in EXECUTION_MODES:
        raise StudyError(f"unknown execution_mode {execution_mode!r}")
    chosen_matrix = matrix or ("diagnostic" if scope == "diagnostic" else "pairwise")
    if chosen_matrix not in MATRICES_BY_SCOPE[scope]:
        raise StudyError(
            f"matrix {chosen_matrix!r} is not offered for scope {scope!r}; "
            f"choose from {', '.join(MATRICES_BY_SCOPE[scope])}"
        )
    if scope == "diagnostic" and chosen_matrix != "diagnostic":
        raise StudyError("the diagnostic scope uses the curated matrix only; select scope=family for other designs")
    # Scope-dependent default: the curated diagnostic matrix fixes seeds 0 and 1
    # (0 for the main cells, 1 for the held-out stability cell), while a family
    # design multiplies every vector by the seed list and therefore defaults to
    # one seed.  An explicit --seeds overrides both.
    if seeds is None:
        seeds = [0, 1] if scope == "diagnostic" else [0]
    registry = _load_registry(root)
    verify_family(registry)
    if scope == "diagnostic":
        cases = diagnostic_cases(root, seeds=seeds)
        selected = list(PRIMARY)
    else:
        cases = family_cases(root, matrix=chosen_matrix, seeds=seeds)
        selected = list(FAMILY)
    cases, excluded = _exclude_ungated(cases, execution_mode=execution_mode, scope=scope)
    if not cases:
        raise StudyError("every selected case was excluded (no behavioural reference); refusing an empty manifest")
    full_case_count = len(cases)
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise StudyError("shard_index must be in [0, shard_count) and shard_count must be positive")
    if shard_count > 1:
        # Deterministic and disjoint: sorted case ids, round-robin assignment.
        cases = [case for position, case in enumerate(sorted(cases, key=lambda c: str(c["case_id"])))
                 if position % shard_count == shard_index]
        if not cases:
            raise StudyError(
                f"shard {shard_index}/{shard_count} selected no cases; reduce shard_count"
            )
    plan = build_plan(
        cases,
        scope=scope,
        matrix=chosen_matrix,
        seeds=seeds,
        provider=provider,
        model=model,
        api_base=api_base,
        wire_api=wire_api,
        reasoning_effort=reasoning_effort,
        max_api_calls=max_api_calls,
        max_tokens_total=max_tokens_total,
        max_wall_seconds=max_wall_seconds,
        max_steps=max_steps,
        max_tokens=max_tokens,
        invalid_retries=invalid_retries,
        excluded=excluded,
        shard={"index": shard_index, "count": shard_count},
    )

    live_environments = sorted({str(case["environment"]) for case in cases})
    environments = [_environment_record(root, registry, name) for name in live_environments]
    for environment in environments:
        environment["difficulty_vector_count"] = sum(
            1 for case in cases if case["environment"] == environment["environment"]
        )
    issues = [f"{env['environment']}: {issue}" for env in environments for issue in env["issues"]]
    config_paths = sorted({root / env["config_path"] for env in environments})
    inventory_digest = hashlib.sha256(
        "\n".join(f"{path.relative_to(root).as_posix()}\t{_sha256(path)}" for path in config_paths).encode("utf-8")
    ).hexdigest()
    commit = _git_value(root, "rev-parse", "HEAD")
    dirty = bool((_git_value(root, "status", "--porcelain") or "").strip())
    manifest = {
        "schema_version": 1,
        "manifest_type": "rl_eval_generator_suite",
        "created_at": created_at or _utc_now(),
        "repository": {
            "commit": commit,
            "pinned_revision": commit,
            "dirty": dirty,
            "root": str(root),
        },
        "inventory": {
            "config_paths_sha256": inventory_digest,
            "comparison_refs": [],
        },
        "selection": {
            "matrix": chosen_matrix,
            "seeds": list(seeds),
            "families": [],
            "selected_levels": [],
            "expand_interventions": False,
            "dry_run": False,
            "max_tokens_total": max_tokens_total,
            "environments": live_environments,
        },
        "registry_audit": {
            "registry_path": "envs/registry.yaml",
            "registered_environment_count": len(registry),
            "selected_environment_count": len(live_environments),
            "missing_registry_paths": [],
            "unregistered_config_paths": [],
            "duplicate_registry_paths": {},
            "selected_only": True,
        },
        "families": [],
        "family_count": 0,
        "intervention_case_count": 0,
        "branch_comparisons": [],
        "environment_count": len(environments),
        "case_count": len(cases),
        "environments": environments,
        "cases": cases,
        "issues": issues,
        "ready_for_scheduler": not issues and all(case["status"] in {"planned", "ready"} for case in cases),
        "study": {
            "profile": {"name": PROFILE_NAME, "version": PROFILE_VERSION},
            "scope": scope,
            "matrix": chosen_matrix,
            "seeds": list(seeds),
            "execution_mode_context": execution_mode,
            "family": list(FAMILY),
            "family_selected": selected,
            "live_environments": live_environments,
            "excluded_environments": excluded,
            "condition_map": {name: CONDITIONS.get(name, "family_member") for name in live_environments},
            "provider": provider,
            "model": model,
            "api_base": api_base or None,
            "wire_api": wire_api,
            "reasoning_effort": reasoning_effort,
            "limits": plan["limits"],
            "per_case_limits": plan["per_case_limits"],
            "worst_case": plan["worst_case"],
            "case_ids": plan["case_ids"],
            "full_case_count": full_case_count,
            "shard": {"index": shard_index, "count": shard_count},
            "decision_checks": {name: list(DECISION_CHECKS.get(name, ())) for name in live_environments},
            "axis_pins": {
                name: {
                    axis_id: {"level": level, "reason": reason}
                    for axis_id, (level, reason) in AXIS_PINS.get(name, {}).items()
                }
                for name in live_environments
                if name in AXIS_PINS
            },
        },
    }
    return manifest, plan


def _git_value(root: Path, *args: str) -> str | None:
    import subprocess

    try:
        result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


# ---------------------------------------------------------------------------
# Writing the provider-free artefacts
# ---------------------------------------------------------------------------


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def plan_markdown(manifest: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    study = manifest["study"]
    lines = [
        f"# {PROFILE_NAME} {PROFILE_VERSION} - provider-free plan",
        "",
        f"- **Scope:** `{plan['scope']}` (matrix `{plan['matrix']}`)",
        f"- **Provider / model:** `{plan['provider']}` / `{plan['model']}`"
        + (f" (api_base `{plan['api_base']}`)" if plan.get("api_base") else ""),
        f"- **Wire API:** `{plan['wire_api']}`"
        + (f", reasoning `{plan['reasoning_effort']}`" if plan.get("reasoning_effort") else ""),
        f"- **Cases:** {plan['case_count']} across {len(plan['environments'])} environment(s)",
        f"- **Seeds:** {', '.join(str(seed) for seed in plan['seeds'])}",
        f"- **Per episode:** max_steps={plan['per_case_limits']['max_steps']}, "
        f"max_tokens={plan['per_case_limits']['max_tokens']}, "
        f"invalid_retries={plan['per_case_limits']['invalid_retries']}",
        "",
        "## Worst-case budget (provider-free arithmetic)",
        "",
        f"- API calls: **{plan['worst_case']['api_calls']}** "
        f"(ceiling {plan['limits']['max_api_calls']})",
        f"- Output tokens: **{plan['worst_case']['output_tokens']}** "
        f"(ceiling {plan['limits']['max_tokens_total']})",
        f"- Wall clock: estimate **{int(plan['worst_case']['estimated_wall_seconds'])} s**, "
        f"minimum accepted **{int(plan['worst_case']['minimum_wall_seconds'])} s** "
        f"(ceiling {int(plan['limits']['max_wall_seconds'])} s)",
        "",
        "A ceiling is enforced by the controller; it is not a label. The plan fails closed",
        "when it does not fit, and this profile has no compile-only path.",
        "",
        "## Conditions",
        "",
    ]
    for condition in sorted(set(study["condition_map"].values())):
        names = [name for name, value in study["condition_map"].items() if value == condition]
        lines.append(f"- `{condition}`: {', '.join(f'`{name}`' for name in names)}")
    if study["excluded_environments"]:
        lines += ["", "## Excluded from live scored evaluation", ""]
        for entry in study["excluded_environments"]:
            lines.append(
                f"- `{entry['environment']}` - {entry['reason']} "
                f"({entry['dropped_case_count']} planned case(s) dropped): {entry['detail']}"
            )
    lines += ["", "## Cases", "", "| # | case id | condition | factor | expectation |", "|---|---|---|---|---|"]
    for index, case in enumerate(manifest["cases"], start=1):
        meta = case.get("study", {})
        lines.append(
            f"| {index} | `{case['case_id']}` | `{case['condition']}` | "
            f"`{meta.get('factor')}` | {meta.get('expectation')} |"
        )
    lines += [
        "",
        "## Not in this plan",
        "",
        "- No provider request is made in `plan_only`; the live step stops before provider",
        "  access if the oracle preflight or the exact-instance gate fails.",
        "- Scores are never pooled across the expanded control and the recursive discovery",
        "  condition; see the report contract in `tools/recursive_gluing_study.py`.",
        "",
    ]
    return "\n".join(lines)


def write_plan_artifacts(
    out_dir: Path,
    manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "study_manifest.json"
    plan_path = out_dir / "plan.json"
    markdown_path = out_dir / "plan.md"
    _write_json(manifest_path, manifest)
    _write_json(plan_path, plan)
    markdown_path.write_text(plan_markdown(manifest, plan) + "\n", encoding="utf-8")
    return {
        "manifest": str(manifest_path),
        "plan": str(plan_path),
        "markdown": str(markdown_path),
    }


# ---------------------------------------------------------------------------
# Launching the existing controller
# ---------------------------------------------------------------------------


def run_study(
    manifest: Mapping[str, Any],
    *,
    execution_mode: str,
    provider: str,
    model: str,
    output_dir: Path,
    api_key_env: str = "SUITE_API_KEY",
    api_base: str | None = None,
    wire_api: str = "chat_completions",
    reasoning_effort: str | None = None,
    max_api_calls: int | None = None,
    max_tokens_total: int | None = None,
    max_wall_seconds: float | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    invalid_retries: int = DEFAULT_INVALID_RETRIES,
    temperature: float = 0.0,
    max_retries: int = 3,
    max_http_attempts: int | None = None,
    provider_min_interval_seconds: float = 0.0,
    floor_effect_after: int | None = 3,
    gate_context_sha: str | None = None,
    dry_run: bool = False,
    runner: Any = None,
) -> dict[str, Any]:
    """Forward one dispatch to ``tools.run_suite.run_suite``.

    The provider credential is referenced by *name* (``api_key_env``); no value
    crosses this function, so nothing here can write it to a checkpoint, an
    artifact, or a command line.  ``runner`` is injectable so the wiring can be
    tested without Docker, a judge, or a provider.
    """

    if execution_mode not in {"gates_only", "live"}:
        raise StudyError("run_study executes gates_only or live; plan_only writes the plan only")
    study = manifest.get("study")
    if not isinstance(study, Mapping):
        raise StudyError("manifest has no study block; rebuild it with tools/recursive_gluing_study.py")
    # Fail closed *before* the controller is constructed: an environment the
    # exact-instance gate cannot certify has no behavioural reference, so a
    # score from it would be unverified.  Planning already drops such cases;
    # this refuses a hand-edited or stale manifest that smuggled one back in.
    gated = _gated_environments()
    ungated = sorted(
        {str(case.get("environment")) for case in manifest.get("cases") or []} - gated
    )
    if ungated:
        raise StudyError(
            "refusing to run: no exact-instance behavioural reference for "
            + ", ".join(ungated)
            + "; the gate cannot certify those cases, and this profile has no compile-only path"
        )
    limits = study.get("limits") or {}
    if max_api_calls is None:
        max_api_calls = limits.get("max_api_calls")
    if max_tokens_total is None:
        max_tokens_total = limits.get("max_tokens_total")
    if max_wall_seconds is None:
        max_wall_seconds = limits.get("max_wall_seconds")
    if not max_api_calls or not max_tokens_total or not max_wall_seconds:
        raise StudyError("explicit max_api_calls, max_tokens_total and max_wall_seconds are required")
    plan = build_plan(
        manifest.get("cases", []),
        scope=str(study.get("scope")),
        matrix=str(study.get("matrix")),
        seeds=list(study.get("seeds") or []),
        provider=provider,
        model=model,
        api_base=api_base,
        wire_api=wire_api,
        reasoning_effort=reasoning_effort,
        max_api_calls=int(max_api_calls),
        max_tokens_total=int(max_tokens_total),
        max_wall_seconds=float(max_wall_seconds),
        max_steps=max_steps,
        max_tokens=max_tokens,
        invalid_retries=invalid_retries,
        excluded=list(study.get("excluded_environments") or []),
        shard=study.get("shard") or {"index": 0, "count": 1},
    )
    if runner is None:
        from tools.run_suite import run_suite as runner
    checkpoint = runner(
        manifest,
        output_dir=Path(output_dir),
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        api_base=api_base,
        sandbox="docker",
        max_steps=max_steps,
        max_tokens=max_tokens,
        temperature=temperature,
        invalid_retries=invalid_retries,
        max_retries=max_retries,
        max_http_attempts=max_http_attempts,
        provider_min_interval_seconds=provider_min_interval_seconds,
        max_api_calls=int(max_api_calls),
        max_tokens_total=int(max_tokens_total),
        max_wall_seconds=float(max_wall_seconds),
        floor_effect_after=floor_effect_after,
        wire_api=wire_api,
        reasoning_effort=reasoning_effort,
        checkpoint_path=Path(output_dir) / "suite_checkpoint.json",
        dry_run=dry_run,
        gate_context_sha=gate_context_sha,
        stop_after_gates=execution_mode == "gates_only",
    )
    return {"plan": plan, "checkpoint": checkpoint}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _resolve_run_dir(row: Mapping[str, Any], root: Path) -> Path | None:
    value = row.get("run_dir")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path if path.is_dir() else None


def _usage_for(run_dir: Path | None) -> dict[str, Any]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "latency_ms": 0}
    if run_dir is None:
        return usage
    path = run_dir / "model_responses.jsonl"
    if not path.is_file():
        return usage
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        block = record.get("usage") if isinstance(record, dict) else None
        if not isinstance(block, dict):
            continue
        usage["calls"] += 1
        usage["prompt_tokens"] += int(block.get("prompt_tokens") or 0)
        usage["completion_tokens"] += int(block.get("completion_tokens") or 0)
        usage["latency_ms"] += int(record.get("latency_ms") or 0)
    return usage


def classify_result(
    row: Mapping[str, Any] | None,
    final: Mapping[str, Any],
    *,
    decision_checks: Sequence[str] = (),
    gate_failed: bool = False,
) -> str:
    """One case's outcome, in the vocabulary the report promises.

    Order matters: a gate failure cannot be a score, a provider failure cannot be
    a model failure, and a missing row cannot be an unsatisfiability result.
    """

    if gate_failed:
        return OUTCOME_ORACLE
    if row is None:
        return OUTCOME_MISSING
    status = str(row.get("status") or "")
    if status == "paused_provider_error":
        return OUTCOME_PROVIDER
    if status == "blocked_config_drift":
        return OUTCOME_ORACLE
    if status in {"infrastructure_error", "paused_infrastructure_error"}:
        mode = str(row.get("failure_mode") or final.get("failure_mode") or "")
        if mode in {"judge_runtime_error", "reward_denial"}:
            return OUTCOME_ORACLE
        return OUTCOME_INFRASTRUCTURE
    if status != "scored":
        return OUTCOME_MISSING
    mode = str(row.get("failure_mode") or final.get("failure_mode") or "")
    if mode == "timeout":
        return OUTCOME_TIMEOUT
    if row.get("judge_guarantee") == "compile_only":
        return OUTCOME_COMPILE_ONLY
    checks = final.get("checks") if isinstance(final.get("checks"), Mapping) else {}
    if mode in {"patch_missing", "patch_invalid", "source_invalid", "artifact_missing", "runtime_error"}:
        return OUTCOME_MALFORMED
    verdict = row.get("verdict")
    score = row.get("score")
    if verdict == "PASS" and isinstance(score, (int, float)) and float(score) >= 1.0:
        return OUTCOME_VALIDATED_SUCCESS
    if decision_checks and checks:
        if any(check in checks and checks[check] is False for check in decision_checks):
            return OUTCOME_WRONG_DECISION
    return OUTCOME_SCORED_FAILURE


def _numeric_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[Any]] = {}
    for row in rows:
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        for key, value in metrics.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.setdefault(str(key), []).append(value)
    summary: dict[str, Any] = {}
    for key, samples in sorted(values.items()):
        unique = sorted({float(sample) for sample in samples})
        summary[key] = {
            "count": len(samples),
            "min": min(samples),
            "max": max(samples),
            "mean": round(sum(samples) / len(samples), 6),
            "distinct": unique if len(unique) <= 8 else len(unique),
        }
    return summary


def _merge_checkpoints(checkpoints: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge shard checkpoints without letting two rows claim one case id.

    Shards are disjoint by construction (the manifest assigns case ids
    round-robin), so a repeated case id means two dispatches graded the same
    case.  That is not a merge: it is reported, and the first row wins.
    """

    merged: dict[str, Any] = {"results": [], "shards": []}
    seen: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    for index, checkpoint in enumerate(checkpoints):
        run = checkpoint.get("run") if isinstance(checkpoint.get("run"), Mapping) else {}
        merged["shards"].append(
            {
                "index": index,
                "manifest_commit": run.get("manifest_commit"),
                "provider": run.get("provider"),
                "model": run.get("model"),
                "recorded_cases": len(checkpoint.get("results") or []),
                "paused": bool(checkpoint.get("paused")),
                "pause_reason": checkpoint.get("pause_reason"),
            }
        )
        for row in checkpoint.get("results") or []:
            if not isinstance(row, dict):
                continue
            case_id = str(row.get("case_id"))
            if case_id in seen:
                conflicts.append({"case_id": case_id, "first_shard": seen[case_id], "repeated_in": str(index)})
                continue
            seen[case_id] = str(index)
            merged["results"].append(row)
        if isinstance(checkpoint.get("instance_gate"), Mapping):
            merged.setdefault("instance_gate", checkpoint["instance_gate"])
        for key in ("paused", "pause_reason", "provider_free_validation_complete"):
            if key not in merged and key in checkpoint:
                merged[key] = checkpoint[key]
    merged["conflicting_case_ids"] = conflicts
    if checkpoints:
        merged["run"] = dict(checkpoints[0].get("run") or {})
    return merged


def build_report(
    manifest: Mapping[str, Any],
    checkpoint: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    gate_report: Mapping[str, Any] | None = None,
    oracle_report: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Machine-readable report: per environment, per factor, per hidden check.

    There is deliberately no overall pass rate.  The expanded control and the
    recursive discovery condition answer different questions, and the family
    members are different tasks; a single number over them would be the
    misleading metric this study exists to avoid.
    """

    root = Path(root)
    if checkpoint is None:
        merged_checkpoint: dict[str, Any] = {}
    elif isinstance(checkpoint, Mapping):
        merged_checkpoint = dict(checkpoint)
    else:
        merged_checkpoint = _merge_checkpoints(list(checkpoint))
    checkpoint = merged_checkpoint
    study = dict(manifest.get("study") or {})
    cases = list(manifest.get("cases") or [])
    rows = {str(row.get("case_id")): row for row in checkpoint.get("results") or [] if isinstance(row, dict)}
    gate_failed = bool(gate_report) and not gate_report.get("instance_coverage_complete", False)
    case_rows: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id"))
        row = rows.get(case_id)
        run_dir = _resolve_run_dir(row, root) if row else None
        final = _read_json(run_dir / "final.json") if run_dir else {}
        checks = final.get("checks") if isinstance(final.get("checks"), Mapping) else {}
        metrics = final.get("metrics") if isinstance(final.get("metrics"), Mapping) else {}
        study_meta = case.get("study") if isinstance(case.get("study"), Mapping) else {}
        outcome = classify_result(
            row,
            final,
            decision_checks=DECISION_CHECKS.get(str(case.get("environment")), ()),
            gate_failed=gate_failed,
        )
        case_rows.append(
            {
                "case_id": case_id,
                "environment": case.get("environment"),
                "condition": case.get("condition", "family_member"),
                "factor": study_meta.get("factor"),
                "expectation": study_meta.get("expectation"),
                "difficulty": case.get("difficulty"),
                "difficulty_levels": case.get("difficulty_levels"),
                "seed": case.get("seed"),
                "outcome": outcome,
                "verdict": row.get("verdict") if row else None,
                "score": row.get("score") if row else None,
                "failure_mode": row.get("failure_mode") if row else None,
                "judge_guarantee": row.get("judge_guarantee") if row else None,
                "checks": {str(name): bool(value) for name, value in checks.items()},
                "metrics": dict(metrics),
                "usage": _usage_for(run_dir),
                "elapsed_seconds": row.get("elapsed_seconds") if row else None,
                "http_attempts": row.get("http_attempts") if row else None,
                "error": row.get("error") if row else None,
                "run_dir": str(run_dir) if run_dir else None,
                "generation_id": row.get("generation_id") if row else None,
                "pair_id": row.get("pair_id") if row else None,
            }
        )
    environments: list[dict[str, Any]] = []
    for environment in sorted({str(case.get("environment")) for case in cases}):
        subset = [entry for entry in case_rows if entry["environment"] == environment]
        counts = {outcome: 0 for outcome in OUTCOMES}
        for entry in subset:
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        check_names = sorted({name for entry in subset for name in entry["checks"]})
        checks = {
            name: {
                "passed": sum(1 for entry in subset if entry["checks"].get(name) is True),
                "failed": sum(1 for entry in subset if entry["checks"].get(name) is False),
                "observed": sum(1 for entry in subset if name in entry["checks"]),
            }
            for name in check_names
        }
        scored = [entry for entry in subset if entry["outcome"] in {OUTCOME_VALIDATED_SUCCESS, OUTCOME_SCORED_FAILURE, OUTCOME_WRONG_DECISION, OUTCOME_MALFORMED}]
        environments.append(
            {
                "environment": environment,
                "condition": CONDITIONS.get(environment, "family_member"),
                "case_count": len(subset),
                "outcomes": counts,
                "scored_case_count": len(scored),
                "validated_success_count": counts[OUTCOME_VALIDATED_SUCCESS],
                "checks": checks,
                "metrics": _numeric_metrics(subset),
                "factors": sorted({str(entry["factor"]) for entry in subset if entry["factor"]}),
            }
        )
    factors: list[dict[str, Any]] = []
    for factor in sorted({str(entry["factor"]) for entry in case_rows if entry["factor"]}):
        subset = [entry for entry in case_rows if entry["factor"] == factor]
        counts = {outcome: 0 for outcome in OUTCOMES}
        for entry in subset:
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        factors.append(
            {
                "factor": factor,
                "condition": sorted({str(entry["condition"]) for entry in subset})[0] if subset else None,
                "case_count": len(subset),
                "outcomes": counts,
            }
        )
    conditions: list[dict[str, Any]] = []
    for condition in sorted({str(entry["condition"]) for entry in case_rows}):
        subset = [entry for entry in case_rows if entry["condition"] == condition]
        counts = {outcome: 0 for outcome in OUTCOMES}
        for entry in subset:
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        conditions.append(
            {
                "condition": condition,
                "case_count": len(subset),
                "environments": sorted({str(entry["environment"]) for entry in subset}),
                "outcomes": counts,
                "note": "counts only; this condition is never pooled with another",
            }
        )
    manifest_cases = [str(case.get("case_id")) for case in cases]
    extra_rows = sorted(set(rows) - set(manifest_cases))
    run = checkpoint.get("run") if isinstance(checkpoint.get("run"), Mapping) else {}
    return {
        "schema_version": 1,
        "profile": {"name": PROFILE_NAME, "version": PROFILE_VERSION},
        "study": {
            "scope": study.get("scope"),
            "matrix": study.get("matrix"),
            "seeds": study.get("seeds"),
            "condition_map": study.get("condition_map"),
            "family": study.get("family"),
            "live_environments": study.get("live_environments"),
            "excluded_environments": study.get("excluded_environments") or [],
        },
        "run": {
            "manifest_commit": run.get("manifest_commit") or (manifest.get("repository") or {}).get("commit"),
            "provider": run.get("provider") or study.get("provider"),
            "model": run.get("model") or study.get("model"),
            "api_base": run.get("api_base") or study.get("api_base"),
            "wire_api": run.get("wire_api") or study.get("wire_api"),
            "reasoning_effort": run.get("reasoning_effort") or study.get("reasoning_effort"),
            "api_key_env": run.get("api_key_env"),
            "sandbox": run.get("sandbox"),
            "limits": {
                "max_api_calls": run.get("max_api_calls"),
                "max_tokens_total": run.get("max_tokens_total"),
                "max_steps": run.get("max_steps"),
                "max_tokens": run.get("max_tokens"),
                "max_http_attempts": run.get("max_http_attempts"),
                "invalid_retries": run.get("invalid_retries"),
            },
            "estimated_total_api_calls": run.get("estimated_total_api_calls"),
            "estimated_total_output_tokens": run.get("estimated_total_output_tokens"),
            "paused": bool(checkpoint.get("paused")),
            "pause_reason": checkpoint.get("pause_reason"),
            "gate_context_sha": (checkpoint.get("instance_gate") or {}).get("gate_context_sha"),
            "provider_free_validation_complete": checkpoint.get("provider_free_validation_complete"),
            "shards": checkpoint.get("shards") or [],
            "conflicting_case_ids": checkpoint.get("conflicting_case_ids") or [],
        },
        "manifest": {
            "case_count": len(cases),
            "case_ids": manifest_cases,
            "environment_count": len(environments),
            "environments": [entry["environment"] for entry in environments],
            "config_sha256": {
                str(env.get("environment")): env.get("config_sha256")
                for env in manifest.get("environments") or []
            },
            "unexpected_result_rows": extra_rows,
            "shard": (manifest.get("study") or {}).get("shard"),
            "full_case_count": (manifest.get("study") or {}).get("full_case_count"),
        },
        "gate": {
            "reported": bool(gate_report),
            "instance_coverage_complete": (gate_report or {}).get("instance_coverage_complete"),
            "provider_calls": (gate_report or {}).get("provider_calls"),
            "cases": [
                {
                    "case_id": row.get("case_id"),
                    "environment": row.get("environment"),
                    "status": row.get("status"),
                    "reason": row.get("reason"),
                }
                for row in (gate_report or {}).get("cases") or []
                if isinstance(row, dict)
            ],
            "oracle_preflight": {
                "model_sweep_allowed": (oracle_report or {}).get("model_sweep_allowed"),
                "behavioral_coverage_complete": (oracle_report or {}).get("behavioral_coverage_complete"),
                "unverified_environments": (oracle_report or {}).get("unverified_environments"),
            },
            "excluded_environments": study.get("excluded_environments") or [],
        },
        "cross_condition_aggregation": "none",
        "conditions": conditions,
        "environments": environments,
        "factors": factors,
        "cases": case_rows,
        "usage": {
            "prompt_tokens": sum(entry["usage"].get("prompt_tokens", 0) for entry in case_rows),
            "completion_tokens": sum(entry["usage"].get("completion_tokens", 0) for entry in case_rows),
            "provider_calls": sum(entry["usage"].get("calls", 0) for entry in case_rows),
        },
        "notes": [
            "No pooled score is reported across the expanded control, the recursive discovery "
            "condition, or the family members.",
            "A timeout, a missing row, or an oracle/gate failure is never counted as a model "
            "failure and never read as evidence of unsatisfiability.",
        ],
    }


def _csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for entry in report["cases"]:
        checks = entry.get("checks") or {}
        failed = sorted(name for name, value in checks.items() if value is False)
        rows.append(
            {
                "case_id": entry["case_id"],
                "environment": entry["environment"],
                "condition": entry["condition"],
                "factor": entry["factor"],
                "difficulty": entry["difficulty"],
                "seed": entry["seed"],
                "outcome": entry["outcome"],
                "verdict": entry["verdict"],
                "score": entry["score"],
                "failure_mode": entry["failure_mode"],
                "judge_guarantee": entry["judge_guarantee"],
                "failed_checks": ";".join(failed),
                "passed_check_count": sum(1 for value in checks.values() if value),
                "check_count": len(checks),
                "unfolded_occurrences": (entry.get("metrics") or {}).get("unfolded_occurrences"),
                "recursive_depth": (entry.get("metrics") or {}).get("recursive_depth"),
                "gluing_regime": (entry.get("metrics") or {}).get("gluing_regime"),
                "label_mode": (entry.get("metrics") or {}).get("label_mode"),
                "elapsed_seconds": entry["elapsed_seconds"],
                "prompt_tokens": (entry.get("usage") or {}).get("prompt_tokens"),
                "completion_tokens": (entry.get("usage") or {}).get("completion_tokens"),
                "http_attempts": entry["http_attempts"],
                "error": entry["error"],
            }
        )
    return rows


REPORT_CSV_FIELDS = (
    "case_id",
    "environment",
    "condition",
    "factor",
    "difficulty",
    "seed",
    "outcome",
    "verdict",
    "score",
    "failure_mode",
    "judge_guarantee",
    "failed_checks",
    "passed_check_count",
    "check_count",
    "unfolded_occurrences",
    "recursive_depth",
    "gluing_regime",
    "label_mode",
    "elapsed_seconds",
    "prompt_tokens",
    "completion_tokens",
    "http_attempts",
    "error",
)


def report_markdown(report: Mapping[str, Any]) -> str:
    run = report["run"]
    study = report["study"]
    lines = [
        f"# {PROFILE_NAME} {PROFILE_VERSION} - results",
        "",
        f"- **Scope:** `{study['scope']}` (matrix `{study['matrix']}`)",
        f"- **Provider / model:** `{run['provider']}` / `{run['model']}`"
        + (f" (`{run['api_base']}`)" if run.get("api_base") else ""),
        f"- **Code commit:** `{run['manifest_commit']}`",
        f"- **Wire API / reasoning:** `{run['wire_api']}` / `{run['reasoning_effort']}`",
        f"- **Cases:** {report['manifest']['case_count']}",
        f"- **Gate:** instance coverage complete = "
        f"`{report['gate']['instance_coverage_complete']}`",
        "- **Aggregation:** none across conditions (counts are reported per condition)",
        "",
        "## Outcomes by condition",
        "",
        "| condition | cases | validated success | scored failure | wrong decision | malformed | provider | infra | gate | timeout | missing |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for condition in report["conditions"]:
        outcomes = condition["outcomes"]
        lines.append(
            f"| `{condition['condition']}` | {condition['case_count']} | "
            f"{outcomes.get(OUTCOME_VALIDATED_SUCCESS, 0)} | {outcomes.get(OUTCOME_SCORED_FAILURE, 0)} | "
            f"{outcomes.get(OUTCOME_WRONG_DECISION, 0)} | {outcomes.get(OUTCOME_MALFORMED, 0)} | "
            f"{outcomes.get(OUTCOME_PROVIDER, 0)} | {outcomes.get(OUTCOME_INFRASTRUCTURE, 0)} | "
            f"{outcomes.get(OUTCOME_ORACLE, 0)} | {outcomes.get(OUTCOME_TIMEOUT, 0)} | "
            f"{outcomes.get(OUTCOME_MISSING, 0)} |"
        )
    lines += ["", "## Per environment", ""]
    for environment in report["environments"]:
        lines += [
            f"### `{environment['environment']}` ({environment['condition']})",
            "",
            f"- Cases: {environment['case_count']} (scored: {environment['scored_case_count']}, "
            f"validated success: {environment['validated_success_count']})",
            f"- Factors: {', '.join(f'`{factor}`' for factor in environment['factors'])}",
        ]
        outcomes = {name: count for name, count in environment["outcomes"].items() if count}
        lines.append(f"- Outcomes: {outcomes}")
        if environment["checks"]:
            lines += ["", "| hidden check | passed | failed |", "|---|---|---|"]
            for name, block in environment["checks"].items():
                lines.append(f"| `{name}` | {block['passed']} | {block['failed']} |")
        if environment["metrics"]:
            rendered = ", ".join(
                f"`{key}` mean={block['mean']} (min {block['min']}, max {block['max']})"
                for key, block in environment["metrics"].items()
            )
            lines += ["", f"- Judge metrics: {rendered}"]
        lines.append("")
    if report["study"]["excluded_environments"]:
        lines += ["## Excluded from live scored evaluation", ""]
        for entry in report["study"]["excluded_environments"]:
            lines.append(f"- `{entry['environment']}`: {entry['reason']} - {entry['detail']}")
        lines.append("")
    lines += ["## Case detail", "", "| case | condition | factor | outcome | verdict | score | failed checks |", "|---|---|---|---|---|---|---|"]
    for entry in report["cases"]:
        failed = sorted(name for name, value in (entry["checks"] or {}).items() if value is False)
        lines.append(
            f"| `{entry['case_id']}` | `{entry['condition']}` | `{entry['factor']}` | "
            f"`{entry['outcome']}` | {entry['verdict']} | {entry['score']} | "
            f"{', '.join(f'`{name}`' for name in failed) or '-'} |"
        )
    lines += [
        "",
        "## Reading this report",
        "",
        "- `validated_success` requires a scored PASS under the exact-instance oracle gate; a",
        "  PASS labelled `compile_only` is reported separately and is never a validated success.",
        "- `timeout_or_resource_budget_exhaustion`, `missing_result`, `oracle_or_gate_failure`,",
        "  `provider_failure` and `infrastructure_failure` are not model scores.",
        "- No total pass rate is computed: the expanded control, the recursive discovery",
        "  condition and the family members answer different questions.",
        "",
    ]
    return "\n".join(lines)


def write_report_artifacts(out_dir: Path, report: Mapping[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    csv_path = out_dir / "results.csv"
    md_path = out_dir / "summary.md"
    _write_json(json_path, report)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORT_CSV_FIELDS))
        writer.writeheader()
        for row in _csv_rows(report):
            writer.writerow({key: row.get(key) for key in REPORT_CSV_FIELDS})
    md_path.write_text(report_markdown(report) + "\n", encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _split_seeds(value: str | None) -> list[int] | None:
    if value is None or not value.strip():
        return None
    seeds = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            seeds.append(int(item))
        except ValueError as exc:
            raise StudyError(f"seeds must be comma-separated integers, got {value!r}") from exc
    if not seeds:
        raise StudyError("seeds resolved to an empty list")
    return seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser, *, include_provider: bool) -> None:
        target.add_argument("--scope", choices=SCOPES, default="diagnostic")
        target.add_argument("--matrix", default=None, help="diagnostic (default) or pairwise/covering/representative")
        target.add_argument(
        "--seeds",
        default=None,
        help="comma-separated seeds; diagnostic defaults to its fixed 0,1 and family to 0",
    )
        target.add_argument("--out", type=Path, required=True)
        if include_provider:
            target.add_argument("--execution-mode", choices=EXECUTION_MODES, default="plan_only")
            target.add_argument("--provider", choices=PROVIDERS, default="agentrouter")
            target.add_argument("--model", required=False, default="PLACEHOLDER-SET-ME")
            target.add_argument("--api-base", default=None)
            target.add_argument("--wire-api", choices=("chat_completions", "responses"), default="chat_completions")
            target.add_argument("--reasoning-effort", default=None)
            target.add_argument("--max-api-calls", type=int, default=2000)
            target.add_argument("--max-tokens-total", type=int, default=8_000_000)
            target.add_argument("--max-wall-seconds", type=float, default=14_400)

    plan_parser = sub.add_parser("plan", help="build the filtered manifest and provider-free budget plan")
    add_common(plan_parser, include_provider=True)
    plan_parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    plan_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    plan_parser.add_argument("--invalid-retries", type=int, default=DEFAULT_INVALID_RETRIES)
    plan_parser.add_argument("--shard-index", type=int, default=0)
    plan_parser.add_argument("--shard-count", type=int, default=1)
    plan_parser.add_argument("--created-at", default=None, help=argparse.SUPPRESS)
    plan_parser.add_argument("--print", dest="print_manifest", action="store_true", help="print the plan JSON")

    run_parser = sub.add_parser("run", help="run gates_only or live through tools/run_suite.py")
    run_parser.add_argument("--manifest", type=Path, required=True)
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument("--execution-mode", choices=("gates_only", "live"), required=True)
    run_parser.add_argument("--provider", choices=PROVIDERS, required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--api-key-env", default="SUITE_API_KEY")
    run_parser.add_argument("--api-base", default=None)
    run_parser.add_argument("--wire-api", choices=("chat_completions", "responses"), default="chat_completions")
    run_parser.add_argument("--reasoning-effort", default=None)
    run_parser.add_argument("--max-api-calls", type=int, default=None)
    run_parser.add_argument("--max-tokens-total", type=int, default=None)
    run_parser.add_argument("--max-wall-seconds", type=float, default=None)
    run_parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    run_parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    run_parser.add_argument("--invalid-retries", type=int, default=DEFAULT_INVALID_RETRIES)
    run_parser.add_argument("--temperature", type=float, default=0.0)
    run_parser.add_argument("--max-retries", type=int, default=3)
    run_parser.add_argument("--max-http-attempts", type=int, default=None)
    run_parser.add_argument("--provider-min-interval-seconds", type=float, default=0.0)
    run_parser.add_argument("--gate-context-sha", default=None)
    run_parser.add_argument("--dry-run", action="store_true")

    report_parser = sub.add_parser("report", help="write JSON/CSV/Markdown results from a checkpoint")
    report_parser.add_argument("--manifest", type=Path, required=True)
    report_parser.add_argument(
        "--run-out",
        type=Path,
        action="append",
        required=True,
        help="controller output directory; repeat for one entry per shard",
    )
    report_parser.add_argument("--out", type=Path, required=True)
    report_parser.add_argument("--root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            manifest, plan = build_study_manifest(
                scope=args.scope,
                matrix=args.matrix,
                seeds=_split_seeds(args.seeds),
                execution_mode=args.execution_mode,
                provider=args.provider,
                model=args.model,
                api_base=args.api_base,
                wire_api=args.wire_api,
                reasoning_effort=args.reasoning_effort or None,
                max_api_calls=args.max_api_calls,
                max_tokens_total=args.max_tokens_total,
                max_wall_seconds=args.max_wall_seconds,
                max_steps=args.max_steps,
                max_tokens=args.max_tokens,
                invalid_retries=args.invalid_retries,
                shard_index=args.shard_index,
                shard_count=args.shard_count,
                created_at=args.created_at,
            )
            paths = write_plan_artifacts(args.out, manifest, plan)
            if args.print_manifest:
                print(json.dumps(plan, indent=2))
            else:
                print(json.dumps({"plan": plan, "paths": paths}, indent=2))
            return 0
        if args.command == "run":
            manifest = _read_json(args.manifest)
            result = run_study(
                manifest,
                execution_mode=args.execution_mode,
                provider=args.provider,
                model=args.model,
                output_dir=args.out,
                api_key_env=args.api_key_env,
                api_base=args.api_base,
                wire_api=args.wire_api,
                reasoning_effort=args.reasoning_effort or None,
                max_api_calls=args.max_api_calls,
                max_tokens_total=args.max_tokens_total,
                max_wall_seconds=args.max_wall_seconds,
                max_steps=args.max_steps,
                max_tokens=args.max_tokens,
                invalid_retries=args.invalid_retries,
                temperature=args.temperature,
                max_retries=args.max_retries,
                max_http_attempts=args.max_http_attempts,
                provider_min_interval_seconds=args.provider_min_interval_seconds,
                gate_context_sha=args.gate_context_sha,
                dry_run=args.dry_run,
            )
            checkpoint = result["checkpoint"]
            print(
                json.dumps(
                    {
                        "cases": len(manifest.get("cases") or []),
                        "execution_mode": args.execution_mode,
                        "provider_free_validation_complete": bool(
                            checkpoint.get("provider_free_validation_complete")
                        ),
                        "recorded_cases": len(checkpoint.get("results") or []),
                        "paused": bool(checkpoint.get("paused")),
                        "pause_reason": checkpoint.get("pause_reason"),
                    },
                    indent=2,
                )
            )
            if checkpoint.get("paused"):
                return 3
            return 0
        if args.command == "report":
            manifest = _read_json(args.manifest)
            run_dirs = list(args.run_out)
            checkpoints = [_read_json(path / "suite_checkpoint.json") for path in run_dirs]
            gate_report = next(
                (report for report in (_read_json(path / "instance_oracles.json") for path in run_dirs) if report),
                {},
            )
            oracle_report = next(
                (report for report in (_read_json(path / "oracle_preflight.json") for path in run_dirs) if report),
                {},
            )
            report = build_report(
                manifest,
                checkpoints,
                gate_report=gate_report or None,
                oracle_report=oracle_report or None,
                root=args.root,
            )
            paths = write_report_artifacts(args.out, report)
            print(json.dumps({"paths": paths, "cases": report["manifest"]["case_count"]}, indent=2))
            return 0
        raise StudyError(f"unknown command {args.command!r}")
    except (OSError, ValueError, StudyError) as exc:
        print(f"recursive-gluing study failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
