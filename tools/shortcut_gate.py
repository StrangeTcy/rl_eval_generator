#!/usr/bin/env python3
"""Validate an environment's shortcut corpus: the patches, and what they claim.

A shortcut is a patch that satisfies the measurement while leaving the task unfixed. The
corpus is therefore a claim about the *evaluator*, and it is checkable in two layers:

* **Static (blocking, CI, no torch).** Each patch exists, applies to a freshly generated
  instance at its declared difficulty vector, touches only files the source validator lets
  an agent patch, and never edits the tests or the judge - a "shortcut" that rewrites
  `visible_tests.py` is not gaming the measurement, it is deleting it, and it teaches
  nothing about the measurement.  The declarations are checked too, because a corpus is an
  argument: `credits_under` must include the authoritative view (a patch that fails it is a
  bad attempt, never rewarded, uninformative); credits and withholds must be disjoint and
  must name views the environment declares; a view that judges the *run* rather than the
  artifact may not be given a verdict (`trajectory_gated` is `not_measurable` for a scripted
  apply, so it belongs in `run_dependent`, and `adversarial` needs a `perturbation` the
  adversary can actually execute); and every view listed in `strictness_evidence` must be
  demonstrated by some entry - a stricter measurement nobody has ever fooled is an untested
  claim of strictness.
  * **Behavioral (`--judge`, needs torch).** Apply the patch, grade it, and require the
  verdict to match the declaration: credited where it claims to pass, withheld where it
  claims to fail. That is the tier that catches a shortcut which is actually a fix, and a
  declaration that was wishful.

`--judge` degrades to a reported skip when torch is absent, so the corpus can be checked
in a plain CI job without pretending the behavioral tier passed.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import evaluator_views as ev  # noqa: E402

COSTLY_OR_UNAVAILABLE = {"adversarial", "trajectory_gated"}


def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=kwargs.pop("cwd", ROOT), capture_output=True, text=True, **kwargs)


def load_corpus(env_dir: Path) -> tuple[dict[str, Any], list[str]]:
    index = env_dir / "shortcuts" / "index.yaml"
    if not index.is_file():
        return {}, []
    data = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
    problems: list[str] = []
    if data.get("environment") != env_dir.name:
        problems.append(
            f"{index}: environment is {data.get('environment')!r}, not {env_dir.name!r}"
        )
    entries = data.get("shortcuts") or []
    if not entries:
        problems.append(f"{index}: lists no shortcuts")
    seen: set[str] = set()
    for entry in entries:
        where = f"{index}: shortcut {entry.get('id')!r}"
        if not isinstance(entry, dict) or not entry.get("id"):
            problems.append(f"{index}: every shortcut needs an id")
            continue
        if entry["id"] in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(entry["id"])
        for field in ("patch", "difficulty", "credits_under", "withholds_credit_under"):
            if not entry.get(field):
                problems.append(f"{where}: missing '{field}'")
        patch = env_dir / "shortcuts" / str(entry.get("patch") or "")
        if not patch.is_file():
            problems.append(f"{where}: patch file {entry.get('patch')!r} does not exist")
    return data, problems


def check_patch_application(entry: dict[str, Any], env_name: str, env_dir: Path) -> list[str]:
    """Generate the declared instance and make sure the patch lands on it cleanly."""
    problems: list[str] = []
    workspace = tempfile.mkdtemp(prefix="shortcut-")
    try:
        name = Path(workspace).name + "-inst"
        generated = _run(
            [sys.executable, "generate_env.py", "--env", env_name, "--name", name,
             "--difficulty", str(entry["difficulty"]), "--seed", str(entry.get("seed", 0)),
             "--no-manifest"],
            cwd=ROOT,
        )
        if generated.returncode != 0:
            return [f"{entry['id']}: instance generation failed: "
                    + (generated.stdout + generated.stderr)[-400:]]
        instance = ROOT / name
        try:
            touched = _patch_targets(env_dir / "shortcuts" / str(entry["patch"]))
            patchable = _patchable_files(instance)
            for rel in touched:
                if "judge/" in rel or "visible_tests" in rel:
                    problems.append(
                        f"{entry['id']}: touches {rel!r}; editing the tests or the judge is "
                        "not gaming the measurement, it is deleting it, and it teaches "
                        "nothing about the measurement"
                    )
                elif patchable and rel.split("/")[-1] not in patchable:
                    problems.append(
                        f"{entry['id']}: touches {rel!r}, which the source validator does not "
                        "allow an agent to patch, so no agent submission could look like this"
                    )
            applied = _run(["patch", "-p1", "--dry-run", "--silent", "-i",
                            str((env_dir / "shortcuts" / str(entry["patch"])).resolve())],
                           cwd=instance)
            if applied.returncode != 0:
                problems.append(
                    f"{entry['id']}: does not apply to a freshly generated instance at "
                    f"difficulty {entry['difficulty']!r}: "
                    + (applied.stdout + applied.stderr)[-300:]
                )
            else:
                _run(["patch", "-p1", "--silent", "-i",
                      str((env_dir / "shortcuts" / str(entry["patch"])).resolve())],
                     cwd=instance)
                for rel in touched:
                    body = (instance / rel).read_text(encoding="utf-8")
                    if "SHORTCUT" not in body:
                        problems.append(
                            f"{entry['id']}: {rel} has no SHORTCUT marker, so the patch is "
                            "indistinguishable from a legitimate edit in a transcript"
                        )
        finally:
            shutil.rmtree(instance, ignore_errors=True)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return problems


def _patch_targets(patch_path: Path) -> list[str]:
    files: list[str] = []
    for line in patch_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
    return files


def _patchable_files(instance: Path) -> set[str]:
    validator = instance / "judge" / "source_validator.py"
    if not validator.is_file():
        return set()
    for line in validator.read_text(encoding="utf-8").splitlines():
        if line.startswith("PATCHABLE"):
            literal = line.split("=", 1)[1].strip()
            try:
                return {str(item) for item in eval(literal, {"__builtins__": {}}, {})}
            except Exception:
                return set()
    return set()


def check_declarations(
    entries: list[dict[str, Any]], config: dict[str, Any], corpus: dict[str, Any] | None = None
) -> list[str]:
    """Cross-check the per-entry declarations and the corpus-level obligations."""
    corpus = corpus or {}
    problems: list[str] = []
    declared = {str(view) for view in ((config.get("evaluators") or {}).get("views") or [])}
    for entry in entries:
        where = f"shortcut {entry.get('id')!r}"
        credits = {str(view) for view in (entry.get("credits_under") or [])}
        withholds = {str(view) for view in (entry.get("withholds_credit_under") or [])}
        unknown = (credits | withholds) - set(ev.VIEWS)
        if unknown:
            problems.append(f"{where}: names unknown views {sorted(unknown)}")
        if credits & withholds:
            problems.append(
                f"{where}: credits and withholds overlap on {sorted(credits & withholds)}; a "
                "patch cannot both pass and fail the same measurement"
            )
        if declared and not (credits | withholds) <= declared:
            problems.append(
                f"{where}: refers to views this environment does not declare: "
                + ", ".join(sorted((credits | withholds) - declared))
            )
        run_dependent = entry.get("run_dependent") or {}
        if not isinstance(run_dependent, dict):
            problems.append(f"{where}: run_dependent must map a view to why it judges nothing here")
        else:
            for view, reason in run_dependent.items():
                if str(view) not in set(ev.VIEWS):
                    problems.append(f"{where}: run_dependent names unknown view {view!r}")
                elif str(view) in (credits | withholds):
                    problems.append(
                        f"{where}: {view} appears both as a verdict and as run_dependent; a view "
                        "cannot both judge this patch and have nothing to judge"
                    )
                elif not str(reason).strip():
                    problems.append(f"{where}: run_dependent[{view!r}] gives no reason")
        for view in sorted(credits | withholds):
            if view == "trajectory_gated":
                problems.append(
                    f"{where}: lists trajectory_gated among the views it credits or withholds. "
                    "That view reads the agent's event stream, and a corpus entry is applied by a "
                    "script with no episode, so it is not_measurable - unavailable, not a verdict. "
                    "Say so under `run_dependent` and let the trajectory gates carry the claim"
                )
            elif view == "adversarial":
                problems.append(
                    f"{where}: lists adversarial among the views it credits or withholds. That "
                    "view is a second grade under a different evaluator, so record the transform "
                    "in `perturbation`, where the adversary can actually run it"
                )
        perturbation = entry.get("perturbation") or {}
        perturbation_view = str(perturbation.get("view") or "")
        if perturbation_view and perturbation_view not in set(ev.VIEWS):
            problems.append(f"{where}: perturbation names unknown view {perturbation_view!r}")
        elif perturbation_view and perturbation_view != "adversarial":
            problems.append(
                f"{where}: perturbation.view is {perturbation_view!r}; the other views are "
                "projections of the same grade, so there is no second evaluator to perturb"
            )
        elif perturbation_view and not str(perturbation.get("transform") or "").strip():
            problems.append(
                f"{where}: perturbation has no transform, so 'the perturbed evaluator rejects "
                "this too' stays an assertion that nothing runs"
            )
        if not withholds:
            problems.append(
                f"{where}: withholds_credit_under is empty, i.e. this shortcut is claimed to "
                "satisfy every measurement - which would make it a fix, not a shortcut"
            )
    costly = {str(view) for view in ((config.get("evaluators") or {}).get("costly") or [])}
    if "adversarial" in costly and entries:
        missing = sorted(
            str(entry.get("id")) for entry in entries
            if not str((entry.get("perturbation") or {}).get("transform") or "").strip()
        )
        if missing:
            problems.append(
                "no perturbation.transform for " + ", ".join(missing) + ", so this corpus can "
                "never certify that the adversarial view rejects these patches; the environment "
                "declares that view costly, which is exactly the case a second grade exists for"
            )
    authoritative = str((config.get("evaluators") or {}).get("authoritative") or "")
    obligations = [str(view) for view in (corpus.get("strictness_evidence") or [])]
    unknown_obligations = sorted(set(obligations) - declared)
    if unknown_obligations:
        problems.append(
            "strictness_evidence names views this environment does not declare: "
            + ", ".join(unknown_obligations)
        )
    for view in obligations:
        demonstrated = any(
            view in {str(item) for item in (entry.get("withholds_credit_under") or [])}
            and authoritative in {str(item) for item in (entry.get("credits_under") or [])}
            for entry in entries
        )
        if not demonstrated:
            problems.append(
                f"{view} is claimed to be stricter, yet it rejects nothing in this corpus "
                f"that {authoritative or 'the authoritative view'} accepts: the strictness is "
                "an assertion about the measurement with no shortcut standing behind it"
            )
    return problems


def classify_verdict(entry: dict[str, Any], views: dict[str, Any], authoritative: str) -> list[str]:
    """Compare a graded shortcut against what its entry claimed.

    This is the definitional test, not a formality: a patch the authoritative view still
    credits is a shortcut, and one it rejects is just a bad attempt that will never be
    rewarded, so it teaches nothing about the measurement.  A view that comes back
    unavailable or not_run is reported as inconclusive rather than passed - the claim is
    that the view *rejects* this patch, and nothing was observed to reject it.
    """
    problems: list[str] = []
    credits = {str(item) for item in (entry.get("credits_under") or [])}
    withholds = {str(item) for item in (entry.get("withholds_credit_under") or [])}
    if authoritative and authoritative not in credits:
        problems.append(
            f"shortcut {entry.get('id')!r}: declares that it does not satisfy "
            f"{authoritative!r}, but the authoritative view is what a policy is paid on; a "
            "patch that fails it is a bad attempt, not a shortcut"
        )
    states = {name: spec.get("state") for name, spec in views.items()}
    for view in sorted(credits):
        if states.get(view) != "pass":
            problems.append(
                f"shortcut {entry.get('id')!r} was claimed to be credited by {view}, but "
                f"grading returned {states.get(view)!r}: the shortcut is actually rejected by "
                f"{view}, so it is a fix as far as that measurement is concerned"
            )
    for view in sorted(withholds):
        state = states.get(view)
        if state == "pass":
            problems.append(
                f"shortcut {entry.get('id')!r} was claimed to be rejected by {view}, but that "
                "view credited it: the stricter measurement is not actually looking at what "
                "the entry says it looks at"
            )
        elif state not in {"fail", "reward_denial"}:
            problems.append(
                f"shortcut {entry.get('id')!r}: {view} returned {state!r} instead of failing, "
                "so the withholding claim is untested on this run rather than true"
            )
    return problems


def grade_shortcut(env_name: str, entry: dict[str, Any], *, timeout: int = 2100) -> dict[str, Any]:
    """Generate the declared instance, apply the patch, run the real judge, project views."""
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import uuid  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415

    import env_runner  # noqa: PLC0415

    patch_path = ROOT / "envs" / env_name / "shortcuts" / str(entry["patch"])
    out: dict[str, Any] = {"shortcut": entry.get("id"), "status": "error", "views": {}}
    with tempfile.TemporaryDirectory(prefix="shortcut-judge-") as temp:
        old_episodes = env_runner.EPISODES_DIR
        try:
            env_runner.EPISODES_DIR = Path(temp) / "episodes"
            episode_id = "shortcut_" + uuid.uuid4().hex[:12]
            args = SimpleNamespace(
                episode_id=episode_id, env=env_name, difficulty=str(entry["difficulty"]),
                seed=int(entry.get("seed", 0)), max_steps=1, sandbox="local",
                keep_images=False, keep_workspace=True, interventions="",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                env_runner.reset(args)
            state = env_runner._load_state(episode_id)
            applied = subprocess.run(
                ["patch", "-p1", "--silent", "-i", str(patch_path.resolve())],
                cwd=Path(state["episode_dir"]), capture_output=True, text=True,
            )
            if applied.returncode != 0:
                out["error"] = "patch did not apply to the graded instance"
                return out
            with contextlib.redirect_stdout(io.StringIO()):
                env_runner._submit(state, {"confirm": True}, judge_timeout=timeout)
            state = env_runner._load_state(episode_id)
            result = state.get("judge_result") or {}
            if not result:
                out["error"] = "the judge produced no result"
                return out
            config = yaml.safe_load((ROOT / "envs" / env_name / "config.yaml").read_text(encoding="utf-8")) or {}
            pass_score = float((config.get("scoring") or {}).get("pass_score", 1.0))
            out["score"] = result.get("score")
            out["verdict"] = result.get("verdict")
            out["views"] = {
                name: {key: value for key, value in spec.items() if key != "checks"}
                for name, spec in ev.derive(
                    result, pass_score=pass_score, config=config, interventions={}
                ).items()
            }
            out["status"] = "graded"
        except Exception as error:  # a tier that crashes should say so, not pretend
            out["error"] = f"{type(error).__name__}: {error}"
        finally:
            env_runner.EPISODES_DIR = old_episodes
    return out


def judge_shortcuts(env_name: str, entries: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]], bool]:
    """Grade every shortcut and compare the verdict with its declaration (needs torch)."""
    try:
        import torch  # noqa: F401
    except ImportError:
        return ([], [], False)
    config = yaml.safe_load((ROOT / "envs" / env_name / "config.yaml").read_text(encoding="utf-8")) or {}
    authoritative = str((config.get("evaluators") or {}).get("authoritative") or "")
    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    for entry in entries:
        report = grade_shortcut(env_name, entry)
        rows.append(report)
        if report.get("status") != "graded":
            problems.append(
                f"shortcut {entry.get('id')!r}: could not be graded on this machine "
                f"({report.get('error')}) - an ungradeable shortcut is an uncertified claim"
            )
            continue
        problems.extend(classify_verdict(entry, report["views"], authoritative))
    return (problems, rows, True)


def check_env(env_dir: Path, *, run_judge: bool) -> dict[str, Any]:
    env_name = env_dir.name
    config = yaml.safe_load((env_dir / "config.yaml").read_text(encoding="utf-8")) or {}
    data, problems = load_corpus(env_dir)
    entries = list(data.get("shortcuts") or [])
    if entries:
        for entry in entries:
            problems.extend(check_patch_application(entry, env_name, env_dir))
        problems.extend(check_declarations(entries, config, data))
    judged = []
    if run_judge and entries:
        graded, rows, available = judge_shortcuts(env_name, entries)
        problems.extend(graded)
        if not available:
            judged = [f"{env_name}: behavioral tier skipped (no torch in this interpreter)"]
        else:
            for row in rows:
                states = {name: spec.get("state") for name, spec in (row.get("views") or {}).items()}
                judged.append(
                    f"{row.get('shortcut')}: score={row.get('score')} verdict={row.get('verdict')} "
                    + " ".join(f"{name}={state}" for name, state in sorted(states.items()))
                )
    return {
        "environment": env_name,
        "shortcuts": [str(entry.get("id")) for entry in entries],
        "problems": problems,
        "behavioral": judged,
        "ok": not problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", action="append", default=[], help="environment to check; default: all with a corpus")
    parser.add_argument("--judge", action="store_true", help="also grade each shortcut (needs torch)")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.env:
        env_dirs = [ROOT / "envs" / name for name in args.env]
    else:
        env_dirs = sorted(path.parent.parent for path in (ROOT / "envs").rglob("shortcuts/index.yaml"))
    reports = [check_env(path, run_judge=args.judge) for path in env_dirs if (path / "shortcuts").is_dir()]
    if not reports:
        print("no shortcut corpora found", file=sys.stderr)
        return 2
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(reports, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = 0
    for report in reports:
        mark = "ok" if report["ok"] else "FAIL"
        print(f"shortcut gate: {report['environment']} [{mark}] "
              f"{len(report['shortcuts'])} shortcuts")
        for problem in report["problems"]:
            print(f"  - {problem}")
        for note in report["behavioral"]:
            print(f"  ~ {note}")
        total += len(report["problems"])
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
