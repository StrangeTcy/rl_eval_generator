#!/usr/bin/env python3
"""Second measurement: re-grade one submitted artifact under a perturbed evaluator.

`shared/evaluator_views.py` treats `adversarial` as *never implicit*: it needs a second
judge run over the same artifact, so `derive()` reports `state: not_run` unless a
`judge.adversarial.json` sits next to the primary result. This tool is the only thing
that writes that file, and it deliberately knows one perturbation: **re-grade the same
patch on a fresh draw of the instance** (`seed_offset`). That is the measurement adversary
in its weakest, most portable form - the artifact stays byte-identical, the data under it
moves, and an artifact tuned to the measurement rather than to the task loses score.

Anything fancier (a temperature sweep, a queue-order audit) is a claim about a specific
environment's geometry, so it belongs in that environment's `shortcuts/index.yaml` under
`perturbation.transform` as a description the corpus author can be argued with, and it
stays *uncertified* until someone implements it here. Refusing to invent a perturbation
is the point: a "measurement adversary" that silently re-ran the same grade would turn
`not_run` - an honest gap - into `pass`, which is a fabricated number in the exact place
the whole layer exists to protect.

Usage:
    python tools/evaluator_adversary.py --episode <id> [--seed-offset 1] [--json out.json]
    python tools/evaluator_adversary.py --corpus moco [--json out.json]
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT),):
    if path not in sys.path:
        sys.path.insert(0, path)

from shared import evaluator_views as ev  # noqa: E402
from tools import shortcut_gate as sg  # noqa: E402

ADVERSARIAL_RESULT_NAME = "judge.adversarial.json"


def unavailable(reason: str) -> dict[str, Any]:
    """The one shape a failed adversary may take: a gap, never a zero."""
    return {"status": "unavailable", "reason": reason}


def classify_perturbation(
    entry: dict[str, Any], pristine_score: float, perturbed_score: float, pass_score: float
) -> tuple[list[str], dict[str, Any]]:
    """Compare a shortcut's adversarial claim with what the re-grade produced.

    Returns problems plus a row the corpus report can print. The claim is directional: a
    `withholds_adversarial: true` entry asserts the perturbed measurement *rejects* what
    the pristine one accepted, so a perturbed score that still passes contradicts it.
    """
    problems: list[str] = []
    perturbation = entry.get("perturbation") or {}
    claims_rejected = bool(perturbation.get("withholds_adversarial"))
    pristine_passes = float(pristine_score) >= pass_score
    perturbed_passes = float(perturbed_score) >= pass_score
    row = {
        "shortcut": entry.get("id"),
        "pristine_score": float(pristine_score),
        "perturbed_score": float(perturbed_score),
        "drop": round(float(pristine_score) - float(perturbed_score), 6),
        "perturbed_state": "pass" if perturbed_passes else "fail",
    }
    if not pristine_passes:
        problems.append(
            f"shortcut {entry.get('id')!r}: the pristine grade did not pass, so this is not a "
            "shortcut to perturb in the first place"
        )
    elif claims_rejected and perturbed_passes:
        problems.append(
            f"shortcut {entry.get('id')!r}: claimed to be rejected by the adversarial view, "
            f"but the perturbed grade still passes at {float(perturbed_score):g} - either the "
            "perturbation does not touch what this shortcut moved, or the shortcut also "
            "generalises, in which case the measurement is not distinguishing them"
        )
    elif not claims_rejected and not perturbed_passes:
        problems.append(
            f"shortcut {entry.get('id')!r}: declared no adversarial claim, yet the perturbed "
            "grade rejects it, so the corpus is missing evidence that this is a real shortcut"
        )
    return problems, row


def grade_pair(env_name: str, entry: dict[str, Any], *, seed_offset: int, timeout: int) -> dict[str, Any]:
    """Grade the same patch on two draws of the same vector: pristine and perturbed."""
    try:
        import torch  # noqa: F401
    except ImportError:
        return unavailable("no torch in this interpreter, so the judge cannot run")
    import env_runner  # noqa: PLC0415

    patch_path = ROOT / "envs" / env_name / "shortcuts" / str(entry["patch"])
    scores: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="adversary-") as temp:
        old_episodes = env_runner.EPISODES_DIR
        try:
            env_runner.EPISODES_DIR = Path(temp) / "episodes"
            for label, seed in (("pristine", int(entry.get("seed", 0))),
                                ("perturbed", int(entry.get("seed", 0)) + seed_offset)):
                episode_id = f"adv_{label}_{uuid.uuid4().hex[:10]}"
                args = SimpleNamespace(
                    episode_id=episode_id, env=env_name, difficulty=str(entry["difficulty"]),
                    seed=seed, max_steps=1, sandbox="local", keep_images=False,
                    keep_workspace=True, interventions="",
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    env_runner.reset(args)
                state = env_runner._load_state(episode_id)
                applied = subprocess.run(
                    ["patch", "-p1", "--silent", "-i", str(patch_path.resolve())],
                    cwd=Path(state["episode_dir"]), capture_output=True, text=True,
                )
                if applied.returncode != 0:
                    return unavailable(f"the corpus patch did not apply to seed {seed}")
                with contextlib.redirect_stdout(io.StringIO()):
                    env_runner._submit(state, {"confirm": True}, judge_timeout=timeout)
                graded = env_runner._load_state(episode_id).get("judge_result") or {}
                if "score" not in graded:
                    return unavailable(f"the judge produced no score for the {label} grade")
                scores[label] = float(graded.get("score") or 0.0)
                if label == "perturbed":
                    Path(state["episode_dir"], ADVERSARIAL_RESULT_NAME).write_text(
                        json.dumps(graded, indent=2) + "\n", encoding="utf-8"
                    )
                    scores["run_dir"] = str(state["episode_dir"])  # type: ignore[assignment]
        except Exception as error:  # a broken harness must say so, not report a verdict
            return unavailable(f"{type(error).__name__}: {error}")
        finally:
            env_runner.EPISODES_DIR = old_episodes
    return {"status": "graded", **scores}


def run_episode(episode_id: str, *, seed_offset: int, timeout: int) -> dict[str, Any]:
    """Re-grade an existing episode's own submission on a fresh draw and record it."""
    import env_runner  # noqa: PLC0415

    try:
        state = env_runner._load_state(episode_id)
    except (SystemExit, FileNotFoundError) as error:  # the runner exits on an unknown id
        return unavailable(f"no such episode ({error})")
    patch = Path(state["episode_dir"]) / "submission.patch"
    if not patch.is_file():
        return unavailable("this episode has no submission.patch to re-grade")
    source = patch.read_text(encoding="utf-8")
    config = yaml.safe_load((ROOT / "envs" / state["env"] / "config.yaml").read_text(encoding="utf-8")) or {}
    pass_score = float((config.get("scoring") or {}).get("pass_score", 1.0))
    try:
        import torch  # noqa: F401
    except ImportError:
        return unavailable("no torch in this interpreter, so the judge cannot run")
    with tempfile.TemporaryDirectory(prefix="adversary-ep-") as temp:
        old_episodes = env_runner.EPISODES_DIR
        try:
            env_runner.EPISODES_DIR = Path(temp) / "episodes"
            fresh = f"adv_{uuid.uuid4().hex[:10]}"
            args = SimpleNamespace(
                episode_id=fresh, env=state["env"], difficulty=state["difficulty"],
                seed=int(state["seed"]) + seed_offset, max_steps=1, sandbox="local",
                keep_images=False, keep_workspace=True, interventions="",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                env_runner.reset(args)
            new_state = env_runner._load_state(fresh)
            episode_dir = Path(new_state["episode_dir"])
            shutil.copyfile(patch, episode_dir / "submission.patch")
            applied = subprocess.run(
                ["patch", "-p1", "--silent", "-i", str(episode_dir / "submission.patch")],
                cwd=episode_dir, capture_output=True, text=True,
            )
            if applied.returncode != 0:
                return unavailable("the submission did not survive onto the perturbed instance")
            with contextlib.redirect_stdout(io.StringIO()):
                env_runner._submit(new_state, {"confirm": True}, judge_timeout=timeout)
            graded = env_runner._load_state(fresh).get("judge_result") or {}
            if "score" not in graded:
                return unavailable("the judge produced no score for the perturbed grade")
            # The primary result and the perturbed one must be readable side by side, so
            # the file goes into the episode the run actually reported on.
            target = Path(state["episode_dir"]) / ADVERSARIAL_RESULT_NAME
            target.write_text(json.dumps(graded, indent=2) + "\n", encoding="utf-8")
            primary = Path(state["episode_dir"]) / "judge_result.json"
            base = json.loads(primary.read_text(encoding="utf-8")) if primary.is_file() else {}
            views = ev.derive(
                base, pass_score=pass_score, adversarial_result=graded,
                views=[view for view in (
                    (config.get("evaluators") or {}).get("views") or ["outcome_only"]
                ) if view in ev.VIEWS],
            )
            return {
                "status": "graded", "run_dir": str(state["episode_dir"]),
                "adversarial_result": str(target), "seed_offset": seed_offset,
                "perturbed_score": float(graded["score"]), "views": views,
                "dispersion": ev.dispersion(views),
            }
        except (Exception, SystemExit) as error:  # a broken harness reports, never judges
            return unavailable(f"{type(error).__name__}: {error}")
        finally:
            env_runner.EPISODES_DIR = old_episodes


def run_corpus(env_name: str, *, seed_offset: int, timeout: int) -> list[dict[str, Any]]:
    config = yaml.safe_load((ROOT / "envs" / env_name / "config.yaml").read_text(encoding="utf-8")) or {}
    pass_score = float((config.get("scoring") or {}).get("pass_score", 1.0))
    data = yaml.safe_load((ROOT / "envs" / env_name / "shortcuts" / "index.yaml").read_text(encoding="utf-8")) or {}
    rows: list[dict[str, Any]] = []
    for entry in list(data.get("shortcuts") or []):
        result = grade_pair(env_name, entry, seed_offset=seed_offset, timeout=timeout)
        if result.get("status") != "graded":
            rows.append({"shortcut": entry.get("id"), **result})
            continue
        problems, row = classify_perturbation(
            entry, result["pristine"], result["perturbed"], pass_score
        )
        rows.append({**row, "problems": problems,
                     "adversarial_view": {"state": row["perturbed_state"],
                                          "perturbed_score": row["perturbed_score"]}})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--episode", help="episode id whose submission.patch should be re-graded")
    target.add_argument("--corpus", metavar="ENV", help="re-grade every shortcut in an env's corpus")
    parser.add_argument("--seed-offset", type=int, default=1,
                        help="how far to move the instance under the artifact (default 1)")
    parser.add_argument("--timeout", type=int, default=2100)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.seed_offset == 0:
        print("seed_offset 0 is not a perturbation: it re-runs the same measurement", file=sys.stderr)
        return 2

    if args.episode:
        outcome = run_episode(args.episode, seed_offset=args.seed_offset, timeout=args.timeout)
        report = {"mode": "episode", "episode": args.episode, **outcome}
        rows = []
        problems = []
    else:
        rows = run_corpus(args.corpus, seed_offset=args.seed_offset, timeout=args.timeout)
        report = {"mode": "corpus", "environment": args.corpus,
                  "seed_offset": args.seed_offset, "rows": rows}
        problems = [problem for row in rows for problem in (row.get("problems") or [])]

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report.get("status") == "unavailable" or rows and all(
        row.get("status") == "unavailable" for row in rows
    ):
        # Nothing could be measured. Say so and leave no verdict behind - a zero here would
        # read as "the adversary approved" to anything downstream.
        reason = report.get("reason") or (rows[0].get("reason") if rows else "no entries")
        print(f"adversary: not run - {reason}")
        return 0
    if args.episode:
        print(f"adversary: {args.episode} perturbed_score={report.get('perturbed_score')} "
              f"wrote {report.get('adversarial_result')}")
        for name, spec in sorted((report.get("views") or {}).items()):
            print(f"  view {name}: {spec.get('state', 'pass' if spec.get('passed') else 'fail')}")
    else:
        for row in rows:
            if row.get("status") == "unavailable":
                print(f"adversary: {row['shortcut']} not certified ({row['reason']})")
                continue
            print(f"adversary: {row['shortcut']} pristine={row['pristine_score']:g} "
                  f"perturbed={row['perturbed_score']:g} drop={row['drop']:g} "
                  f"-> {row['perturbed_state']}")
    for problem in problems:
        print(f"  - {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
