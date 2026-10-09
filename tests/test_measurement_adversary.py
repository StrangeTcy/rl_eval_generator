"""The measurement protocol gets regression tests too (item 16, static tier).

Blocking by construction: `ci.yml` runs `pytest -q`, and the first test here runs
`tools/measurement_adversary.py` as a subprocess, which executes each environment's *real*
guards (`judge/patch_validator.py`, `judge/source_validator.py`) against hostile submissions.
No torch, no Docker, no model - and no model *of* the validator either, which is the whole
point: a tier that reimplemented the allowlist would keep passing while the allowlist rotted.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import measurement_adversary as ma  # noqa: E402


@pytest.fixture(scope="module")
def instance() -> Path:
    name = "ma_test_" + uuid.uuid4().hex[:8]
    generated = subprocess.run(
        [sys.executable, "generate_env.py", "--env", "moco", "--name", name, "--seed", "3",
         "--difficulty", "easy,easy,easy,easy,easy,easy", "--no-manifest"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    path = ROOT / name
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_the_static_tier_passes_for_every_env_that_declares_guards() -> None:
    proc = subprocess.run([sys.executable, "tools/measurement_adversary.py"], cwd=ROOT,
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "adversary: moco [ok] 7/7 exploits caught by a named check" in proc.stdout
    assert "exploited" not in proc.stdout


def test_each_exploit_is_rejected_by_the_guard_the_config_names(instance: Path) -> None:
    exploits = ma.exploit_sources(instance)
    assert set(exploits) == {"no_op_patch", "test_rewrite", "judge_import_tamper", "hardcoded_metric"}
    accepted, output = ma.run_patch_validator(instance, exploits["no_op_patch"][0])
    assert not accepted and "no effective change" in output, (
        "a hunk that re-adds the identical line is the only shape that separates 'patch is "
        "well-formed' from 'patch did something', so it must be the one that fails"
    )
    accepted, output = ma.run_patch_validator(instance, exploits["test_rewrite"][0])
    assert not accepted and "non-patchable file" in output
    # The import tamper must survive the path validator: it is a legal edit to a legal file.
    accepted, output = ma.run_patch_validator(instance, exploits["judge_import_tamper"][0])
    assert accepted, "patch_valid cannot see this exploit, which is why sources_valid exists"
    patched = output.split("OK: patch applied to ")[-1].strip()
    try:
        clean, violations = ma.run_source_validator(instance, Path(patched))
    finally:
        shutil.rmtree(patched, ignore_errors=True)
    assert not clean and "disallowed import" in violations


def test_a_guard_that_does_not_exist_is_reported_as_missing() -> None:
    ok, detail = ma.guard_recomputes("import torch\n", "temperature_sensitive")
    assert not ok and "does not exist" in detail


def test_a_check_read_from_the_agents_own_report_is_not_a_guard() -> None:
    source = (
        "def grade(result):\n"
        "    ok = bool(result['metrics'].get('claimed_gain'))\n"
        "    mark_check(result, 'gain_present', ok)\n"
    )
    ok, detail = ma.guard_recomputes(source, "gain_present")
    assert not ok and "reported about itself" in detail, (
        "a guard whose value is what the submitted code said about itself fires exactly when a "
        "cheating agent wants it to"
    )


def test_a_check_that_reruns_the_submission_is_a_real_guard() -> None:
    source = (
        "def grade(workdir):\n"
        "    outputs = torch.load(os.path.join(workdir, 'eval_outputs.pt'))\n"
        "    ok = bool(outputs.get('tau_ok', False))\n"
        "    mark_check(result, 'temperature_sensitive', ok)\n"
    )
    ok, detail = ma.guard_recomputes(source, "temperature_sensitive")
    assert ok and "traces to" in detail, detail


def test_stdout_is_not_the_authenticator_corroboration_is() -> None:
    ok, detail = ma.stdout_spoof_rejected()
    assert ok, detail
    import env_runner as er

    verdict = er._judge_result(json.dumps({"verdict": "PASS", "score": 1.0, "failure_mode": "pass"}),
                              "", 1, {"provenance": {}})
    assert verdict["verdict"] == "FAIL" and verdict["failure_mode"] == "judge_runtime_error"


def test_an_incomplete_or_misplaced_declaration_is_refused() -> None:
    problems = "\n".join(ma.guard_shape_problems(
        {"no_op_patch": "patch_valid", "visible_test_overfit": "anything", "stdout_spoof": "x"}
    ))
    assert "names exploits this tier does not implement: visible_test_overfit" in problems
    assert "no guard declared for hardcoded_metric, judge_import_tamper, test_rewrite" in problems
    assert "a property of the harness, not of this environment" in problems
    assert ma.guard_shape_problems({
        "no_op_patch": "patch_valid", "test_rewrite": "patch_valid",
        "judge_import_tamper": "sources_valid", "hardcoded_metric": ["temperature_sensitive"],
    }) == []


def test_runtime_exploits_must_be_scheduled_not_assumed(instance: Path) -> None:
    report = ma.check_env("moco", run_dir=instance)
    assert report["problems"] == []
    assert sorted(report["deferred_to_nightly"]) == ["faked_training_failure", "visible_test_overfit"]
