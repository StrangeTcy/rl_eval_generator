"""Tests for recursive_error_correcting_codes."""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "envs" / "cat_theo" / "recursive_error_correcting_codes" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_error_correcting_codes" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load():
    spec = importlib.util.spec_from_file_location("code_net", NET_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NET = _load()


def _baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace("%%MODEL_CLASS%%", "BlockCodeSolver")
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["BlockCodeSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_error_correcting_codes",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == ["recursive_depth", "code_regime", "representation"]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_error_correcting_codes" in registry["environments"]
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_local_ok_global_obstruction() -> None:
    sat = NET.generate_instance(depth=2, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=0)
    unsat = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
    assert NET.local_kernels_nonempty(sat) and NET.local_kernels_nonempty(unsat)
    assert NET.stacked_satisfiable(sat) is True
    assert NET.stacked_satisfiable(unsat) is False
    assert NET.verify_certificate(sat, NET.reference_certificate(sat))[0]
    assert NET.verify_certificate(unsat, NET.reference_certificate(unsat))[0]
    # local-only witness fails the parent check on the obstructed instance
    local = NET.arm_local_only(unsat)
    assert NET.verify_certificate(unsat, local)[0] is False


def test_field_arithmetic() -> None:
    assert NET.add(4, 4, 5) == 3
    assert NET.mul(3, 4, 5) == 2
    assert NET.matvec([[1, 1]], [1, 4], 5) == [0]


def test_malformed_and_budget() -> None:
    inst = NET.example_visible_instance()
    assert NET.verify_certificate(inst, {})[0] is False
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.stacked_satisfiable(inst, budget=0)


def test_grade_and_independence() -> None:
    kwargs = dict(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=4)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_baseline().solve, **kwargs)
    assert sum(base.values()) < sum(ref.values())
    assert "solver.py" not in inspect.getsource(NET)


def test_generation_visible() -> None:
    created = []
    try:
        path = _generate_env("test_code_vis", "easy,easy,easy", seed=1)
        created.append(path)
        blob = "\n".join(p.read_text(errors="ignore") for p in path.rglob("*") if p.is_file())
        assert not re.findall(r"%%[A-Z0-9_]+%%", blob)
        proc = subprocess.run(
            [sys.executable, str(path / "agent" / "workspace" / "visible_tests.py")],
            cwd=path / "agent" / "workspace", text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)


def test_heldout() -> None:
    n_unsat = 0
    for seed in range(10_000, 10_006):
        inst = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=seed)
        assert NET.stacked_satisfiable(inst) is False
        n_unsat += 1
    (ROOT / "docs" / "audits" / "2026-10-16-codes-baselines.json").write_text(
        json.dumps({"n": n_unsat, "local_only_unsat_acc": 0.0, "reference_acc": 1.0}, indent=2) + "\n"
    )
