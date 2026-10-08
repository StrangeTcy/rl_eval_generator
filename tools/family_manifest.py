#!/usr/bin/env python3
"""Build a provider-free representative manifest for one environment family.

Family selection is deliberately derived from ``suite_inventory`` and the
registry paths, not from a second hand-maintained list.  This is useful in a
workflow after ``tools/model_preflight.py`` has succeeded: it creates the
manifest for the intended family without making another provider request.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.artifacts import write_json  # noqa: E402
from tools.suite_inventory import build_manifest  # noqa: E402

FAMILY_ALIASES = {
    "ml_debugging": {"track": "ml_debugging"},
    "category_theoretic": {"track": "category_theoretic_compositional"},
    "recurrent_depth": {"track": "recurrent_depth_behavioral"},
    "trajectory_semantics": {"track": "trajectory_solver_synthesis"},
    "weird_machine": {"track": "weird_machine"},
    "epistemic_games": {"environment": "epistemic_games"},
}


def select_family(manifest: dict[str, Any], family: str) -> dict[str, Any]:
    normalized = family.strip().lower()
    if normalized == "all":
        return manifest
    selector = FAMILY_ALIASES.get(normalized)
    if selector is None:
        raise ValueError(
            f"unknown family {family!r}; choose from all, {', '.join(sorted(FAMILY_ALIASES))}"
        )
    environments = [
        item for item in manifest.get("environments", [])
        if (
            selector.get("track") is not None
            and item.get("track") == selector["track"]
        )
        or (
            selector.get("environment") is not None
            and item.get("environment") == selector["environment"]
        )
    ]
    names = {str(item.get("environment")) for item in environments}
    cases = [case for case in manifest.get("cases", []) if case.get("environment") in names]
    selected = dict(manifest)
    selected["environments"] = environments
    selected["cases"] = cases
    selected["environment_count"] = len(environments)
    selected["case_count"] = len(cases)
    selected["selection"] = {
        **dict(manifest.get("selection") or {}),
        "family": normalized,
    }
    selected["family"] = normalized
    selected["ready_for_scheduler"] = bool(
        manifest.get("ready_for_scheduler") and environments and cases
    )
    if not environments:
        selected.setdefault("issues", []).append(f"family {normalized!r} selected no environments")
        selected["ready_for_scheduler"] = False
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True)
    parser.add_argument("--matrix", choices=("representative", "covering", "all"), default="representative")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            root=ROOT,
            matrix=args.matrix,
            seeds=[args.seed],
            preflight=args.preflight,
            dry_run=True,
        )
        selected = select_family(manifest, args.family)
        write_json(args.out, selected)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"family manifest failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "manifest": str(args.out),
                "family": selected.get("family", "all"),
                "environment_count": selected["environment_count"],
                "case_count": selected["case_count"],
                "ready_for_scheduler": selected["ready_for_scheduler"],
            },
            indent=2,
        )
    )
    return 0 if selected["ready_for_scheduler"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
