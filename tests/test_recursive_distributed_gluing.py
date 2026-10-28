"""Tests for recursive_distributed_gluing."""
from __future__ import annotations

import importlib.util
import inspect
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "envs" / "cat_theo" / "recursive_distributed_gluing" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_distributed_gluing" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load_network():
    spec = importlib.util.spec_from_file_location("dist_net", NET_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NET = _load_network()


def _load_baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace(
        "%%MODEL_CLASS%%", "DistributedTraceSolver"
    )
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["DistributedTraceSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_distributed_gluing",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_and_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == ["recursive_depth", "gluing_regime", "label_opacity"]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_distributed_gluing" in registry["environments"]
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "presheaf", "holonomy", "čech", "cech", "cohomology"):
        assert banned not in prompt
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_trace_not_just_a_number() -> None:
    job = NET.generate_job(depth=2, regime=NET.TREE, opacity=NET.TRANSPARENT, seed=0)
    cert = NET.reference_certificate(job)
    assert cert["status"] == "sat"
    assert cert["trace"]
    assert any(ev["op"] == "spawn" for ev in cert["trace"])
    assert any(ev["op"].startswith("recv:") for ev in cert["trace"])
    ok, _, result = NET.replay_trace(job, cert["trace"])
    assert ok and result == cert["result"]
    assert NET.verify_certificate(job, {"status": "sat", "trace": [], "result": cert["result"]})[0] is False


def test_deadlock_with_local_programs_well_typed() -> None:
    sat = NET.generate_job(depth=2, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, seed=1)
    unsat = NET.generate_job(depth=2, regime=NET.CYCLIC_UNSAT, opacity=NET.TRANSPARENT, seed=1)
    assert NET.job_satisfiable(sat) is True
    assert NET.job_satisfiable(unsat) is False
    for spec in unsat["workers"].values():
        assert spec["program"]


def test_relabel_preserves_sat() -> None:
    job = NET.generate_job(depth=2, regime=NET.TREE, opacity=NET.TRANSPARENT, seed=3)
    twin = NET.relabel_job(job, seed=8)
    assert NET.job_satisfiable(job) is NET.job_satisfiable(twin) is True
    assert set(job["workers"]) != set(twin["workers"])


def test_timeout_is_not_unsat() -> None:
    job = NET.example_visible_job()
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.shortest_trace(job, max_nodes=1)
    assert NET.job_satisfiable(job) is True


def test_grade_reference_beats_baseline() -> None:
    kwargs = dict(depth=2, regime=NET.CYCLIC_UNSAT, opacity=NET.OPAQUE, seed=4)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_load_baseline().solve, **kwargs)
    foil = NET.grade_solver(NET.arm_numbers_only, **kwargs)
    assert base["local_visible"] is True
    assert foil["local_visible"] is False
    assert sum(base.values()) < sum(ref.values())


def test_oracle_independent() -> None:
    assert "solver.py" not in inspect.getsource(NET)
    assert NET.evaluate_solver(lambda _j: {"status": "unsat"}, NET.example_visible_job()) is False


def test_generation_and_visible() -> None:
    created = []
    try:
        for diff in ("easy,easy,easy", "hard,hard,hard"):
            path = _generate_env(f"test_dist_{diff.replace(',', '_')}", diff, seed=2)
            created.append(path)
            blob = "\n".join(p.read_text(errors="ignore") for p in path.rglob("*") if p.is_file())
            assert not re.findall(r"%%[A-Z0-9_]+%%", blob)
        vis = _generate_env("test_dist_visible", "easy,easy,easy", seed=1)
        created.append(vis)
        proc = subprocess.run(
            [sys.executable, str(vis / "agent" / "workspace" / "visible_tests.py")],
            cwd=vis / "agent" / "workspace", text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)

def test_structural_capacity_changes_global_schedulability():
    sat = NET.SchedulerControls().rendezvous(3, 41, 2)
    unsat = NET.SchedulerControls().rendezvous(3, 41, 1)
    assert sat["workers"] == unsat["workers"]
    assert NET.job_satisfiable(sat)
    assert not NET.job_satisfiable(unsat)
    wrong = NET.SchedulerControls().capacity_blind(unsat)
    assert wrong["status"] == "sat"
    assert not NET.verify_certificate(unsat, wrong)[0]


def test_structural_explicit_endpoints_survive_renaming():
    job = NET.generate_job(depth=2, regime=NET.TREE, opacity=NET.TRANSPARENT, seed=41)
    named = NET.SchedulerControls().addresses(job)
    renamed = NET.relabel_job(named, 97)
    assert NET.reference_certificate(job)["result"] == NET.reference_certificate(named)["result"]
    assert NET.reference_certificate(named)["result"] == NET.reference_certificate(renamed)["result"]
    assert NET.verify_certificate(renamed, NET.reference_certificate(renamed))[0]


def test_structural_worker_rules_and_spawn_causality():
    job = NET.example_visible_job()
    job["modulus"] = 7
    job["workers"]["root"]["rule"] = (2, 1, 3)
    job["workers"]["leaf"]["rule"] = (3, 2, 0)
    cert = NET.reference_certificate(job)
    assert cert["result"] == 4
    assert NET.verify_certificate(job, cert)[0]
    premature = ({"agent": "leaf", "op": "compute"},)
    assert not NET.replay_trace(job, list(premature))[0]
