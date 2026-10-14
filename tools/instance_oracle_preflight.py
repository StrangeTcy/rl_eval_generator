#!/usr/bin/env python3
"""Refuse a campaign whose exact-instance reference cannot be applied, before it is billed.

The exact-instance gate (``tools/instance_oracle_gate.py``) patches each generated case and hands
the result to the environment's real judge.  When a reference cannot even produce a patch, the
judge never runs: the row comes back ``oracle_error``, the campaign records
``instance_oracle_coverage_incomplete``, and a tick of provider budget has already been spent to
learn that a literal filename or an exact-text needle went stale against an axis.  Two campaigns
were blocked that way - glyph's ``optimizer`` axis (fixed in 5d142d8) and moco's ``naming`` axis
and ``terminology`` intervention (fixed alongside this file).

This preflight is the same patch path, without the judge: generate, apply the reference, restore,
apply the plausible-wrong variant, require that each changes bytes.  It needs no Docker, no torch
and no provider, so it can run in front of a campaign step.  What it cannot say is the thing the
gate exists to say: whether a *patched* program grades as expected.  A reference that patches
cleanly and still does not solve its instance is a measurement finding, not a defect this file can
see, and the verdicts below are therefore not certification.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402
from tools.instance_oracle_gate import REFERENCES  # noqa: E402


def _workspace_files(root: Path) -> dict[str, str]:
    """Every Python file in a workspace, keyed by path, so a renamed module is still a change."""
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(root.rglob("*.py"))}


def probe_case(case: dict[str, Any]) -> dict[str, Any]:
    """Apply both reference variants to one generated case and report what broke.

    Returns a record only when the case is *not* certifiable by the reference as written: an
    exception (needle absent, ambiguous, or file renamed) or a variant that left the workspace
    byte-identical (a no-op patch cannot certify anything, which is what the gate's per-environment
    refusals in ``instance_oracle_gate.py`` exist to prevent).
    """
    environment = str(case.get("environment"))
    difficulty = str(case.get("difficulty"))
    seed = int(case.get("seed", 0))
    interventions = env_runner._intervention_list(case.get("interventions") or "")
    apply_reference = REFERENCES[environment][0]
    record = {
        "case_id": str(case.get("case_id")),
        "environment": environment,
        "difficulty": difficulty,
        "interventions": interventions,
        "defect": "",
        "detail": "",
    }
    episode_id = "oracle_" + uuid.uuid4().hex[:16]
    arguments = SimpleNamespace(
        episode_id=episode_id, env=environment, difficulty=difficulty, seed=seed, max_steps=1,
        sandbox="local", keep_images=False, keep_workspace=True,
        interventions=",".join(interventions),
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            env_runner.reset(arguments)
        state = env_runner._load_state(episode_id)
        workspace = Path(state["workspace"])
        pristine = Path(state["original_workspace"])
        for variant in ("reference", "plausible_wrong"):
            shutil.rmtree(workspace)
            shutil.copytree(pristine, workspace)
            try:
                apply_reference(workspace, wrong=variant == "plausible_wrong")
            except Exception as exc:  # a reference that cannot reach this vector
                record["defect"] = "reference_cannot_be_applied"
                record["detail"] = f"{type(exc).__name__}: {exc}"
                return record
            if _workspace_files(workspace) == _workspace_files(pristine):
                record["defect"] = "reference_changes_nothing"
                record["detail"] = f"the {variant} patch left the pristine workspace byte-identical"
                return record
    finally:
        shutil.rmtree(ROOT / "episodes" / episode_id, ignore_errors=True)
        episodes = getattr(env_runner, "EPISODES_DIR", None)
        if episodes is not None:
            shutil.rmtree(Path(episodes) / episode_id, ignore_errors=True)
    return record


def preflight(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = list(manifest.get("cases") or [])
    gated = [c for c in cases if str(c.get("environment")) in REFERENCES]
    records = []
    for index, case in enumerate(gated, start=1):
        records.append(probe_case(case))
        if index % 25 == 0:
            print(f"  probed {index}/{len(gated)} gated cases", file=sys.stderr, flush=True)
    blocked = [r for r in records if r["defect"]]
    return {
        "schema_version": 1,
        "cases": len(cases),
        "gated_cases": len(gated),
        "unblockable": not blocked,
        "blocked_cases": blocked,
        "caveat": (
            "patchability only: a case listed as reachable here is not certified. Whether the "
            "reference solves its instance and the plausible-wrong control fails in the predicted "
            "check is measured by the exact-instance gate, which needs the judge."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile", type=Path, help="campaign profile; the plan it ships is probed")
    source.add_argument("--manifest", type=Path, help="manifest JSON with a `cases` list")
    parser.add_argument("--out", type=Path, default=Path("runs/instance_oracle_preflight.json"))
    args = parser.parse_args(argv)

    if args.profile is not None:
        import tools.atria_campaign as atria

        profile = json.loads(json.dumps(_load_yaml(args.profile)))
        manifest = atria.build_manifest(
            root=ROOT,
            matrix=atria.matrix_mode_of(profile),
            seeds=[0],
            expand_interventions=atria.matrix_interventions_of(profile),
        )
        atria._apply_gate_blocked_exclusions(manifest, profile)
    else:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="instance-oracle-preflight-") as tmp:
        env_runner.EPISODES_DIR = Path(tmp) / "episodes"
        result = preflight(manifest)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"gated cases probed: {result['gated_cases']} of {result['cases']}")
    if result["blocked_cases"]:
        print(f"\n{len(result['blocked_cases'])} gated case(s) the current reference cannot certify:\n")
        for record in result["blocked_cases"]:
            print(f"  {record['case_id']}")
            print(f"      {record['defect']}: {record['detail']}")
        print(
            "\nEither extend the reference in tools/instance_oracle_gate.py so it reaches the axis,"
            "\nor omit the case in the profile's manual_gate_blocked_exclusions with the axis named"
            "\nas its calibration_class. Starting the campaign without one of the two converts a"
            "\nten-second finding into a blocked tick."
        )
        return 1
    print("every gated case is reachable by its reference (behavioural certification: no)")
    return 0


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
