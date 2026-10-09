"""Tests for the information_policy contract (decision item 5).

An information policy is the renderer-hook contract applied to evidence
selection: deterministic, pure, shipped to the judge, and re-run there.
These tests cover each claim that makes the module a declaration instead of
prose:

- the purity validator refuses I/O, dynamic code, wall-clock, and async
  policies, and admits sibling-engine imports;
- config validation refuses a policy the layout does not ship to the judge;
- generation records the policy in the manifest and the latent spec, and the
  selection is deterministic (the probe, not just the AST scan);
- ``verify_manifest`` catches a policy edited after generation;
- the epistemic judge (torch-free, runs here for real) passes a reference
  submission with ``information_policy_ok`` and denies reward when either the
  baked record or the shipped module is tampered with;
- the causal_mechanism identity factor now names the policy, and prose twins
  still merge (a constant policy id cannot split a pair).
"""
from __future__ import annotations

import ast
import difflib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import generate_env as ge  # noqa: E402
from shared import generation_manifest as gm  # noqa: E402
from shared import information_policy as ipolicy  # noqa: E402
from shared import latent_spec as ls  # noqa: E402

EPISTEMIC_BASE = "trap,ambiguous,solo,balanced,narrative"
EPISTEMIC_FILES = ROOT / "envs" / "epistemic_games" / "files"
POLICY_SOURCE = EPISTEMIC_FILES / "information_policy.py"


def _generate(name: str, difficulty: str = EPISTEMIC_BASE, seed: int = 3, *extra: str) -> Path:
    directory = ROOT / name
    shutil.rmtree(directory, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, "generate_env.py", "--env", "epistemic_games", "--name", name,
         "--difficulty", difficulty, "--seed", str(seed), *extra],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return directory


def _load_module(name: str, path: Path, extra_path: Path | None = None):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # dataclasses in core.py resolve string annotations via sys.modules, so the
    # module must be registered before exec (the judge does this implicitly by
    # running as a script with its own directory on sys.path).
    sys.modules[name] = module
    if extra_path is not None:
        sys.path.insert(0, str(extra_path))
    try:
        spec.loader.exec_module(module)
    finally:
        if extra_path is not None:
            sys.path.remove(str(extra_path))
    return module


def _reference_patch(tree: Path, patch_path: Path) -> None:
    """Write a submission patch that answers the instance exactly (Bayes-optimal)."""
    judge_dir = tree / "judge"
    inst_spec = ls.parse_instance_spec((judge_dir / "instance_spec.py").read_text(encoding="utf-8"))
    core = _load_module("ip_test_core", judge_dir / "core.py", extra_path=judge_dir)
    instance = core.build_instance(
        template=inst_spec["template"],
        evidence=inst_spec["evidence"],
        prior_id=inst_spec["prior_id"],
        presentation=inst_spec["presentation"],
        framing=inst_spec["framing"],
        seed=inst_spec["seed"],
    )
    answer = {
        "posterior_world1": float(instance.posterior1),
        "verdict": instance.verdict,
        "most_supported": instance.most_supported,
        "justification": "Bayes' rule on the public tables: P(W1|o) = L1*pi1 / (L1*pi1 + L2*pi2).",
    }
    original = (tree / "agent" / "workspace" / "answer.py").read_text(encoding="utf-8")
    submitted = (
        '"""Reference answer computed from the declared public tables."""\n\n'
        "ANSWER = " + repr(answer) + "\n"
    )
    patch_path.write_text(
        "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            submitted.splitlines(keepends=True),
            fromfile="a/answer.py",
            tofile="b/answer.py",
        )),
        encoding="utf-8",
    )


def _run_judge(tree: Path, patch_path: Path) -> tuple[int, dict]:
    env = dict(os.environ)
    env["JUDGE_PATCH_PATH"] = str(patch_path)
    env["JUDGE_ORIGINALS_DIR"] = str(tree / "agent" / "workspace")
    proc = subprocess.run(
        [sys.executable, str(tree / "judge" / "judge.py")],
        capture_output=True, text=True, env=env, timeout=120,
    )
    return proc.returncode, json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# purity validator
# ---------------------------------------------------------------------------

CLEAN_POLICY = '''\
"""A clean policy."""
from __future__ import annotations

import json

import core


def select(context: dict) -> dict:
    return {"POLICY_ID": json.dumps(core.PRIORS, default=str)}
'''


def test_purity_validator_admits_a_clean_sibling_importing_policy() -> None:
    problems = ipolicy.validate_source(
        CLEAN_POLICY, path="policy.py", sibling_modules={"core"}
    )
    assert problems == []


@pytest.mark.parametrize(
    "source, fragment",
    [
        ("import os\n\n\ndef select(context):\n    return {}\n", "os"),
        ("from time import time\n\n\ndef select(context):\n    return {}\n", "time"),
        ("import subprocess\n\n\ndef select(context):\n    return {}\n", "subprocess"),
        ('def select(context):\n    return {"A": open("f").read()}\n', "open()"),
        ('def select(context):\n    return {"A": eval("1")}\n', "eval()"),
        ('def select(context):\n    return {"A": getattr(core, "x")}\n', "getattr()"),
        ("from . import core\n\n\ndef select(context):\n    return {}\n", "relative import"),
        ("import sys\n\n\ndef select(context):\n    return {}\n", "sys"),
        ("async def select(context):\n    return {}\n", "async"),
        ("def choose(context):\n    return {}\n", "select(context)"),
    ],
)
def test_purity_validator_refuses_impure_policies(source: str, fragment: str) -> None:
    problems = ipolicy.validate_source(source, path="policy.py", sibling_modules={"core"})
    assert problems, f"expected {fragment!r} to be refused"
    assert any(fragment in problem for problem in problems), problems


def test_loader_revalidates_and_refuses_a_symlinked_policy(tmp_path: Path) -> None:
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    real = tmp_path / "real_policy.py"
    real.write_text(CLEAN_POLICY.replace("import core\n", "").replace("core.PRIORS", "{}"),
                    encoding="utf-8")
    (files_dir / "policy.py").symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        ipolicy.load_policy(files_dir, "policy.py")


# ---------------------------------------------------------------------------
# config admission: shipped to the judge or refused
# ---------------------------------------------------------------------------

def test_config_validation_refuses_a_policy_the_judge_never_receives() -> None:
    config = ge.load_config("epistemic_games")
    files_dir = ge.find_files_dir("epistemic_games")
    # The real config passes.
    ge.validate_config(config, files_dir, "epistemic_games")

    broken = json.loads(json.dumps(config))
    del broken["layout"]["judge/information_policy.py"]
    with pytest.raises(ValueError, match="not shipped to the judge"):
        ge.validate_config(broken, files_dir, "epistemic_games")

    missing = json.loads(json.dumps(config))
    missing["information_policy"] = "no_such_policy.py"
    with pytest.raises(ValueError, match="file not found"):
        ge.validate_config(missing, files_dir, "epistemic_games")


def test_determinism_probe_refuses_a_stateful_policy(tmp_path: Path) -> None:
    """The AST scan is the coarse gate; the probe is the proof."""
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "policy.py").write_text(
        "import itertools\n\n"
        "_counter = itertools.count()\n\n"
        "def select(context):\n"
        "    return {'N': str(next(_counter))}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not deterministic"):
        ipolicy.check_determinism(files_dir, "policy.py", {"seed": 1, "subs": {}})


# ---------------------------------------------------------------------------
# generation: shipment, records, determinism
# ---------------------------------------------------------------------------

def test_generation_ships_the_policy_and_records_it_everywhere() -> None:
    name = "test_ip_shipment"
    try:
        tree = _generate(name)
        shipped = tree / "judge" / "information_policy.py"
        assert shipped.is_file()
        assert shipped.read_bytes() == POLICY_SOURCE.read_bytes()

        manifest = gm.read_manifest(tree)
        record = manifest["information_policy"]
        assert record["source_path"] == "envs/epistemic_games/files/information_policy.py"
        assert record["sha256"] == ipolicy.sha256_file(POLICY_SOURCE)

        spec = ls.read_spec(tree)
        section = spec["information_policy"]
        assert section["sha256"] == record["sha256"]
        assert section["selection"]["POLICY_ID"] == "epistemic_announcement_v1"
        assert "POLICY_RECORD" in section["selection"]
        # The baked record is a claim about *this* instance's delivery.
        baked = ast.literal_eval(section["selection"]["POLICY_RECORD"])
        assert baked["policy_id"] == "epistemic_announcement_v1"
        assert baked["channel"] == {
            "acknowledged": False, "announcements": 1,
            "delivery": "always", "publicity": "public",
        }
        assert baked["reader_dependence"]["mimicry_holds"] is True
        assert baked["reader_dependence"]["world2_level"] == 3
        assert baked["signal_policy"]["drawn_from_declared_table"] is True
        assert baked["band"]["verdict_matches_band"] is True
        assert baked["support"]["min_likelihood_positive"] is True

        # causal_mechanism is no longer "unavailable": it names the policy.
        mechanism = spec["factors"]["causal_mechanism"]
        assert mechanism == {"POLICY_ID": "epistemic_announcement_v1"}
        identity_mechanism = spec["identity"]["payload"]["factors"]["causal_mechanism"]
        assert identity_mechanism != "unavailable"
        assert len(identity_mechanism) == 64  # a digest, rename-inert

        # The judge template consumed both placeholders.
        judge_src = (tree / "judge" / "judge.py").read_text(encoding="utf-8")
        assert 'POLICY_ID_BAKED = "epistemic_announcement_v1"' in judge_src
        assert "POLICY_RECORD_BAKED = {" in judge_src
        assert "%%POLICY_" not in judge_src
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_policy_selection_is_deterministic_across_generations() -> None:
    config = ge.load_config("epistemic_games")
    levels = ge.parse_difficulty(EPISTEMIC_BASE, config["axes"])
    first = ge.prepare_generation("epistemic_games", "ip_det", levels, seed=3)
    second = ge.prepare_generation("epistemic_games", "ip_det", levels, seed=3)
    assert first["subs"]["POLICY_RECORD"] == second["subs"]["POLICY_RECORD"]
    assert first["information_policy"]["sha256"] == second["information_policy"]["sha256"]


def test_verify_manifest_catches_a_policy_edited_after_generation() -> None:
    name = "test_ip_drift"
    original = POLICY_SOURCE.read_text(encoding="utf-8")
    try:
        tree = _generate(name)
        ok, errors = gm.verify_manifest(tree, config_root=ROOT)
        assert ok, errors

        POLICY_SOURCE.write_text(original + "\n# edited after generation\n", encoding="utf-8")
        ok, errors = gm.verify_manifest(tree, config_root=ROOT)
        assert not ok
        assert any("information_policy sha256 mismatch" in e for e in errors), errors
    finally:
        POLICY_SOURCE.write_text(original, encoding="utf-8")
        shutil.rmtree(ROOT / name, ignore_errors=True)


# ---------------------------------------------------------------------------
# the runtime trap: the judge re-runs the shipped module (torch-free, for real)
# ---------------------------------------------------------------------------

def test_judge_replays_the_policy_and_denies_tampering(tmp_path: Path) -> None:
    name = "test_ip_judge"
    patch_path = tmp_path / "answer.patch"
    try:
        tree = _generate(name)
        _reference_patch(tree, patch_path)

        rc, result = _run_judge(tree, patch_path)
        assert rc == 0, result["notes"]
        assert result["verdict"] == "PASS"
        assert result["score"] == 1.0
        assert result["checks"]["provenance_ok"] is True
        assert result["checks"]["information_policy_ok"] is True

        # Tamper with the baked record: the declaration no longer matches what
        # the shipped module re-derives -> reward_denial, never a pooled zero.
        judge_path = tree / "judge" / "judge.py"
        judge_src = judge_path.read_text(encoding="utf-8")
        judge_path.write_text(
            judge_src.replace("'mimicry_holds': True", "'mimicry_holds': False"),
            encoding="utf-8",
        )
        rc, result = _run_judge(tree, patch_path)
        assert rc == 1
        assert result["failure_mode"] == "reward_denial"
        assert result["checks"]["information_policy_ok"] is False
        assert any("Information-policy replay mismatch" in n for n in result["notes"])
        judge_path.write_text(judge_src, encoding="utf-8")

        # Tamper with the shipped module: the judge re-runs *this file*, so a
        # doctored policy cannot reproduce the baked record either.
        policy_path = tree / "judge" / "information_policy.py"
        policy_src = policy_path.read_text(encoding="utf-8")
        policy_path.write_text(
            policy_src.replace('"publicity": "public",', '"publicity": "private",'),
            encoding="utf-8",
        )
        rc, result = _run_judge(tree, patch_path)
        assert rc == 1
        assert result["failure_mode"] == "reward_denial"
        assert any("Information-policy replay mismatch" in n for n in result["notes"])
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_a_constant_policy_cannot_split_prose_twins() -> None:
    """Item 13 still holds with item 5 in force: dress is not a new task."""
    base_name, twin_name = "test_ip_pair_base", "test_ip_pair_twin"
    try:
        base = _generate(base_name)
        twin = _generate(twin_name, "trap,ambiguous,solo,balanced,bare_table")
        assert gm.read_manifest(twin)["pair_id"] == gm.read_manifest(base)["pair_id"]
        base_spec, twin_spec = ls.read_spec(base), ls.read_spec(twin)
        assert (
            base_spec["identity"]["payload"]["factors"]["causal_mechanism"]
            == twin_spec["identity"]["payload"]["factors"]["causal_mechanism"]
        )
        # The policy id is the identity contribution; the per-instance record
        # lives outside identity precisely so it cannot split the pair.
        assert base_spec["information_policy"]["selection"]["POLICY_ID"] == \
            twin_spec["information_policy"]["selection"]["POLICY_ID"]
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)
