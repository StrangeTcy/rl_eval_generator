#!/usr/bin/env python3
"""Compile a causal experiment specification into counterfactual twin metadata.

This compiler is provider-free and intentionally conservative.  It reuses the
existing suite inventory for base cases, expands baseline/intervention twins,
and marks the result design-only until every intervention has a materializer.
No paid scheduler can accidentally treat a design sketch as a runnable suite.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.artifacts import write_json  # noqa: E402
from arena.experiment_schema import ExperimentSpec, expand_counterfactual_twins  # noqa: E402
from tools.suite_inventory import _load_yaml, build_manifest  # noqa: E402


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _base_cases(spec: ExperimentSpec, document: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    requested = document.get("base_cases")
    cases = [case for case in manifest.get("cases", []) if case.get("environment") == spec.base_environment]
    if requested is None:
        return cases[:1]
    if not isinstance(requested, list) or not requested:
        raise ValueError("base_cases must be a non-empty list when provided")
    selected: list[dict[str, Any]] = []
    for selector in requested:
        if not isinstance(selector, dict):
            raise ValueError("each base_cases selector must be an object")
        environment = selector.get("environment", spec.base_environment)
        difficulty = selector.get("difficulty")
        seed = selector.get("seed", 0)
        matches = [
            case for case in manifest.get("cases", [])
            if case.get("environment") == environment
            and (difficulty is None or case.get("difficulty") == difficulty)
            and case.get("seed") == seed
        ]
        if len(matches) != 1:
            raise ValueError(
                f"base case selector did not resolve to exactly one case: {selector!r} ({len(matches)} matches)"
            )
        selected.append(matches[0])
    return selected


def compile_family(spec_path: Path, out: Path, *, matrix: str = "representative") -> dict[str, Any]:
    document = _load_yaml(spec_path)
    spec_document = document.get("experiment", document)
    if not isinstance(spec_document, dict):
        raise ValueError("experiment spec must contain an object or an experiment object")
    spec = ExperimentSpec.from_dict(spec_document)
    manifest = build_manifest(root=ROOT, matrix=matrix, seeds=[0], dry_run=True)
    base_cases = _base_cases(spec, document, manifest)
    if not base_cases:
        raise ValueError(f"no inventory cases found for base environment {spec.base_environment!r}")
    cases = expand_counterfactual_twins(spec, base_cases)
    unmaterialized = [
        row["variant_id"]
        for row in cases
        if row["variant_id"] != "baseline" and not row["experiment_materialized"]
    ]
    result = {
        "schema_version": 1,
        "manifest_type": "causal_experiment_family",
        "created_at": _utc_now(),
        "ready_for_scheduler": not spec.design_only and not unmaterialized,
        "design_only": spec.design_only,
        "experiment": spec.as_dict(),
        "experiment_spec_sha256": spec.digest(),
        "base_manifest": {
            "repository": manifest.get("repository"),
            "matrix": matrix,
            "base_case_count": len(base_cases),
        },
        "counterfactual_group_count": len({row["twin_group_id"] for row in cases}),
        "case_count": len(cases),
        "cases": cases,
        "safety": {
            "provider_calls": 0,
            "docker_started": False,
            "unmaterialized_interventions": sorted(set(unmaterialized)),
            "reason_not_schedulable": (
                "design_only_spec" if spec.design_only else "intervention_materializer_missing"
            ) if not (not spec.design_only and not unmaterialized) else None,
        },
    }
    write_json(out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--matrix", choices=("representative", "covering", "all"), default="representative")
    args = parser.parse_args(argv)
    try:
        result = compile_family(args.spec, args.out, matrix=args.matrix)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"experiment family compilation failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "out": str(args.out),
                "experiment_id": result["experiment"]["id"],
                "case_count": result["case_count"],
                "ready_for_scheduler": result["ready_for_scheduler"],
                "provider_calls": 0,
            },
            indent=2,
        )
    )
    # A design-only family is a successful compile, not a scheduler failure.
    # The explicit readiness field is the safety gate consumed by dispatchers.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
