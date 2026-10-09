"""Evaluator views: several measurements of one judge run, and the spread between them.

The shipped score is not a neutral quantity. It is one *projection* of a judge result -
the projection that trusts the environment's own pass rule. `D_eval` asks how much the
answer depended on that choice, which is the only way to tell "the agent solved it" from
"the agent satisfied the measurement". A view that a shortcut also satisfies is not
invalid, it is a proxy, and the honest representation is to keep it in the vector and
let the spread say what it is worth.

Nothing here re-runs a judge. Every view except `adversarial` is a pure function of the
result JSON that the single judge run already emitted, plus - for `trajectory_gated` -
the host event log. That is deliberate: an experiment about measurement must hold
behavior fixed, and a second episode would not.

Views that need a second run are `costly`, and a view that needs a transport the run did
not use is `unavailable`. Both are reported as such. A zero from a view nobody computed
would be read as "the agent failed this measurement", which is the one reading the data
cannot support.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Check names emitted by `shared/judge_lib.base_result` that describe the *submission*,
# not the model's behavior. Anything outside this set is treated as a behavioral probe,
# which is what lets the same view definitions apply to all 34 environments without each
# one restating which of its checks are "real".
INFRA_CHECKS = frozenset(
    {
        "patch_found",
        "patch_valid",
        "sources_valid",
        "training_completed",
        "artifact_found",
        "checkpoint_saved",
    }
)

VIEWS: dict[str, dict[str, Any]] = {
    "outcome_only": {
        "description": (
            "The shipped verdict: the environment's own pass rule applied to the judge's "
            "score, with no further requirement."
        ),
        "costly": False,
        "requires": (),
    },
    "integrity_gated": {
        "description": (
            "Credit only if the submission is structurally honest - valid patch, sources "
            "still valid - independent of whether the behavior was learned."
        ),
        "costly": False,
        "requires": (),
    },
    "behavioral_gated": {
        "description": (
            "Credit only if every behavioral probe the judge ran passed, i.e. the hidden "
            "checks that exist precisely because the visible ones can be satisfied "
            "without the fix."
        ),
        "costly": False,
        "requires": (),
    },
    "trajectory_gated": {
        "description": (
            "Outcome plus a trajectory requirement: the agent measured and looked before "
            "it submitted. Needs the host event log, so it is unavailable on the "
            "self-contained run_eval.sh transport."
        ),
        "costly": False,
        "requires": ("host_events",),
    },
    "adversarial": {
        "description": (
            "Outcome under a perturbed re-grade of the same submitted artifact. Needs a "
            "second judge run, so it is opt-in and never implicit."
        ),
        "costly": True,
        "requires": ("second_run",),
    },
}

VIEW_IDS = tuple(VIEWS)
UNAVAILABLE = "unavailable"
NOT_RUN = "not_run"


def _checks(result: Mapping[str, Any]) -> dict[str, bool]:
    checks = result.get("checks") or {}
    return {str(key): bool(value) for key, value in checks.items() if isinstance(checks, dict)}


def _behavioral(checks: Mapping[str, bool]) -> dict[str, bool]:
    return {key: value for key, value in checks.items() if key not in INFRA_CHECKS}


def _passed(result: Mapping[str, Any], pass_score: float) -> bool:
    score = result.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return False
    return float(score) >= pass_score


def derive(
    result: Mapping[str, Any],
    *,
    pass_score: float = 1.0,
    trajectory: Mapping[str, Any] | None = None,
    adversarial_result: Mapping[str, Any] | None = None,
    views: tuple[str, ...] | list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Project one judge result onto every requested measurement.

    `trajectory` is the output of `arena.trajectory_metrics.summarize`; if it says
    `not_measurable`, `trajectory_gated` reports that reason instead of guessing a zero.
    """
    requested = [str(view) for view in (views or VIEW_IDS)]
    unknown = [view for view in requested if view not in VIEWS]
    if unknown:
        raise ValueError(
            f"unknown evaluator view(s): {', '.join(unknown)}; declared views are "
            + ", ".join(VIEW_IDS)
        )
    checks = _checks(result)
    behavioral = _behavioral(checks)
    outcome = _passed(result, pass_score)
    out: dict[str, dict[str, Any]] = {}
    for view in requested:
        if view == "outcome_only":
            out[view] = {
                "passed": outcome,
                "score": float(result.get("score") or 0.0),
                "basis": "the judge's own pass rule",
            }
        elif view == "integrity_gated":
            integrity = all(
                checks.get(name, False) for name in ("patch_valid", "sources_valid")
            )
            out[view] = {
                "passed": bool(outcome and integrity),
                "score": float(result.get("score") or 0.0) if integrity else 0.0,
                "basis": "outcome and a structurally valid submission",
                "integrity_checks": {
                    name: checks.get(name) for name in ("patch_valid", "sources_valid")
                },
            }
        elif view == "behavioral_gated":
            failed = sorted(name for name, value in behavioral.items() if not value)
            out[view] = {
                "passed": bool(outcome and not failed),
                "score": float(result.get("score") or 0.0) if not failed else 0.0,
                "basis": f"outcome and {len(behavioral)} behavioral probe(s)",
                "probes": sorted(behavioral),
                "failed_probes": failed,
            }
        elif view == "trajectory_gated":
            if not trajectory or trajectory.get("status") != "measured":
                out[view] = {
                    "state": UNAVAILABLE,
                    "reason": (trajectory or {}).get("reason")
                    or "no trajectory summary was supplied",
                    "transport_note": (trajectory or {}).get("transport_note", ""),
                }
            else:
                gates = trajectory.get("gates") or {}
                required = ("measured_before_submit", "read_before_first_modify")
                missing = [gate for gate in required if not gates.get(gate)]
                out[view] = {
                    "passed": bool(outcome and not missing),
                    "score": float(result.get("score") or 0.0) if not missing else 0.0,
                    "basis": "outcome plus " + ", ".join(required),
                    "failed_gates": missing,
                }
        elif view == "adversarial":
            if adversarial_result is None:
                out[view] = {
                    "state": NOT_RUN,
                    "reason": (
                        "costly view: it needs a second judge run over the same artifact "
                        "and was not opted into"
                    ),
                }
            else:
                perturbed = _passed(adversarial_result, pass_score)
                out[view] = {
                    "passed": bool(outcome and perturbed),
                    "score": float(adversarial_result.get("score") or 0.0)
                    if perturbed
                    else 0.0,
                    "basis": "outcome survives the perturbed re-grade",
                    "outcome_only_perturbed": perturbed,
                    # Reported even when it does not change the verdict: how far the score
                    # fell under perturbation is the interesting quantity, and reducing it
                    # to pass/fail would throw away the shape of the effect.
                    "perturbed_score": float(adversarial_result.get("score") or 0.0),
                }
    return out


def dispersion(views: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """`D_eval`: how much the answer depended on which measurement was authoritative.

    Computed over the *available* views only, and the excluded ones are named. A spread
    of zero across two views means two measurements agreed, which is a different
    statement from one measurement agreeing with itself.
    """
    scored = {
        name: record
        for name, record in views.items()
        if isinstance(record, Mapping) and "passed" in record
    }
    excluded = sorted(set(views) - set(scored))
    if not scored:
        return {"d_eval": None, "views_compared": 0, "excluded": excluded,
                "reason": "no view could be computed"}
    vector = [1 if record["passed"] else 0 for record in scored.values()]
    scores = [float(record.get("score") or 0.0) for record in scored.values()]
    return {
        "d_eval": round(max(scores) - min(scores), 6) if len(scores) > 1 else 0.0,
        "verdict_disagreement": (max(vector) != min(vector)) if len(vector) > 1 else False,
        "views_compared": len(scored),
        "view_ids": sorted(scored),
        "excluded": excluded,
        "score_vector": {name: round(float(record.get("score") or 0.0), 6)
                         for name, record in sorted(scored.items())},
        "passed": {name: bool(record["passed"]) for name, record in sorted(scored.items())},
        "majority": bool(sum(vector) * 2 >= len(vector)),
        "dispersion_stddev": round(statistics.pstdev(vector), 6) if len(vector) > 1 else 0.0,
    }


def summarize_episode(
    run_dir: Path | str,
    *,
    config: Mapping[str, Any] | None = None,
    pass_score: float = 1.0,
) -> dict[str, Any]:
    """Views and `D_eval` for one finished episode, read back from its run directory."""
    directory = Path(run_dir)
    result: Mapping[str, Any] | None = None
    for name in ("judge_result.json", "final.json"):
        candidate = directory / name
        if candidate.is_file():
            result = json.loads(candidate.read_text(encoding="utf-8"))
            break
    if result is None:
        stdout = directory / "judge.stdout"
        if stdout.is_file():
            from env_runner import _extract_last_json_object  # noqa: PLC0415 - cycle

            result = _extract_last_json_object(stdout.read_text(encoding="utf-8")) or {}
    if not isinstance(result, Mapping) or not result:
        return {
            "status": UNAVAILABLE,
            "reason": "no judge result recorded in the run directory",
            "run_dir": str(directory),
        }
    from arena import trajectory_metrics  # noqa: PLC0415 - optional, host-log reader

    trajectory = trajectory_metrics.summarize(directory.parent / directory.name)
    if trajectory.get("status") != "measured":
        # A run directory keeps the host log beside the artifacts, not in .episodes.
        trajectory = trajectory_metrics.summarize(directory)
    declared = (config or {}).get("views") or list(VIEW_IDS)
    views = derive(
        result,
        pass_score=pass_score,
        trajectory=trajectory,
        adversarial_result=_maybe_adversarial(directory),
        views=declared,
    )
    authoritative = (config or {}).get("authoritative") or "outcome_only"
    return {
        "status": "measured",
        "authoritative_view": authoritative,
        "views": views,
        "d_eval": dispersion(views),
        "authoritative_passed": bool((views.get(authoritative) or {}).get("passed")),
        "trajectory_source": trajectory.get("status"),
    }


def _maybe_adversarial(directory: Path) -> dict[str, Any] | None:
    candidate = directory / "judge.adversarial.json"
    if not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path, help="an episode's run directory")
    parser.add_argument("--config", type=Path, default=None, help="environment config, for its evaluators block")
    parser.add_argument("--pass-score", type=float, default=1.0)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    config = None
    if args.config:
        import yaml

        config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
        config = config.get("evaluators") or {}
    report = summarize_episode(args.run_dir, config=config, pass_score=args.pass_score)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.get("status") == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
