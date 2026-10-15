"""The judge/core grading contract, pinned from both sides.

Every epistemic family grades through one shared judge template line:

    result["checks"]["all_correct"] = grading["checks"]["truth_correct"]

A core whose ``grade()`` omits that key does not fail the submission - it raises
``KeyError`` inside the judge.  The judge then exits with a traceback and no JSON
verdict, ``env_runner._judge_result`` refuses the output as
``judge_runtime_error``, and a campaign row becomes an infrastructure error that
burns the case's whole retry budget without ever measuring the model.
``epistemic_silence`` (checks carried ``posterior_correct``/``direction_correct``)
and ``epistemic_type_games`` (``equilibrium_correct``) shipped exactly that
omission; both now emit the contract key.

These tests hold the contract from both directions - the keys each judge
dereferences out of ``grading["checks"]`` and the keys each core returns,
including the malformed-answer early return, which is the easiest place to lose
one - and then run one real judge end to end per family so a contract break
cannot hide behind a unit-level grade() call.
"""
from __future__ import annotations

import difflib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# One representative vector per family: enough to reach the grading path, which
# is the only path the contract covers.
FAMILIES: dict[str, str] = {
    "epistemic_announcements": "three,one,factual,expedition",
    "epistemic_fragmented_observation": "four,symmetric,expedition",
    "epistemic_nested_knowledge": "four,second,expedition",
    "epistemic_silence": "message,pair,skewed,expedition",
    "epistemic_type_games": "small,mild,expedition",
}

PROBE_DIR = ROOT / "_judge_contract_probe"


def _load_core(family: str):
    spec = importlib.util.spec_from_file_location(
        f"judge_contract_{family}", ROOT / "envs" / family / "files" / "core.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _instance(core, difficulty: str):
    axes = [n for n in inspect.signature(core.build_instance).parameters if n != "seed"]
    return core.build_instance(**dict(zip(axes, difficulty.split(","))), seed=0)


def _judge_reads(family: str) -> set[str]:
    """Every key this family's judge dereferences out of ``grading['checks']``."""
    source = (ROOT / "envs" / family / "files" / "judge.py").read_text(encoding="utf-8")
    reads = set(re.findall(r'grading\["checks"\]\["([a-z_]+)"\]', source))
    reads |= set(re.findall(r'grading\["checks"\]\.get\("([a-z_]+)"', source))
    return reads


def _gradings(core, difficulty: str) -> list[dict]:
    """Grade the ground truth, a mutated truth, and a malformed answer."""
    instance = _instance(core, difficulty)
    truth = core.ground_truth_answer(instance)
    mutated = {k: v for k, v in truth.items() if k != sorted(truth)[0]}
    return [
        instance.grade(truth, 1.0),
        instance.grade(mutated, 1.0),
    ]


@pytest.mark.parametrize("family,difficulty", sorted(FAMILIES.items()))
def test_judge_reads_only_checks_the_core_emits(family: str, difficulty: str) -> None:
    """The contract: no key the judge dereferences may be missing from grade().

    Both grading paths are covered, because a core can satisfy the graded path
    and still drop the key on the early ``answer_format_invalid`` return.
    """
    reads = _judge_reads(family)
    assert reads, f"{family}: the judge dereferences no grading check at all"
    core = _load_core(family)
    for grading in _gradings(core, difficulty):
        missing = sorted(reads - set(grading["checks"]))
        assert not missing, (
            f"{family}: judge reads {sorted(reads)} from grading['checks'] but "
            f"grade() returned {sorted(grading['checks'])} - the judge would raise "
            f"KeyError({missing}) and record judge_runtime_error"
        )


@pytest.mark.parametrize("family,difficulty", sorted(FAMILIES.items()))
def test_judge_scores_a_ground_truth_submission(family: str, difficulty: str, tmp_path: Path) -> None:
    """Run the real judge on a ground-truth patch: it must emit a valid verdict.

    A judge that crashes on a correct submission is indistinguishable from an
    infrastructure failure to a campaign, which is how this contract break
    consumed a case's entire retry budget.
    """
    if PROBE_DIR.exists():
        shutil.rmtree(PROBE_DIR)
    try:
        completed = subprocess.run(
            [sys.executable, "generate_env.py", "--env", family,
             "--name", PROBE_DIR.name, "--difficulty", difficulty, "--seed", "0"],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )
        assert completed.returncode == 0, completed.stderr

        core = _load_core(family)
        truth = core.ground_truth_answer(_instance(core, difficulty))
        original = (PROBE_DIR / "agent" / "workspace" / "answer.py").read_text(encoding="utf-8")
        submitted = '"""Ground-truth submission for the judge contract test."""\n\nANSWER = ' + repr(truth) + "\n"
        patch_path = tmp_path / "agent.patch"
        patch_path.write_text(
            "".join(difflib.unified_diff(
                original.splitlines(keepends=True),
                submitted.splitlines(keepends=True),
                fromfile="a/answer.py", tofile="b/answer.py",
            )),
            encoding="utf-8",
        )

        env = dict(os.environ)
        env["JUDGE_PATCH_PATH"] = str(patch_path)
        env["JUDGE_ORIGINALS_DIR"] = str(PROBE_DIR / "agent" / "workspace")
        proc = subprocess.run(
            [sys.executable, str(PROBE_DIR / "judge" / "judge.py")],
            capture_output=True, text=True, env=env, timeout=300,
        )
        assert proc.stdout.strip(), f"{family}: judge printed no verdict\n{proc.stderr[-2000:]}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])

        # Exactly the shape env_runner._judge_result accepts as a verdict.
        assert result["verdict"] in {"PASS", "FAIL"}
        assert result["verdict"] == ("PASS" if result["score"] >= 1 else "FAIL")
        assert proc.returncode == (0 if result["verdict"] == "PASS" else 1)
        assert isinstance(result["failure_mode"], str)
        assert result["failure_mode"] not in {"", "unknown"}
        assert (result["failure_mode"] == "pass") == (result["verdict"] == "PASS")
        assert result["checks"]["all_correct"] is True, result["checks"]
    finally:
        if PROBE_DIR.exists():
            shutil.rmtree(PROBE_DIR)
