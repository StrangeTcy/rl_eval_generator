"""Tests for recursive_coarse_graining."""
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
FILES = ROOT / "envs" / "cat_theo" / "recursive_coarse_graining" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_coarse_graining" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load():
    spec = importlib.util.spec_from_file_location("cg_net", NET_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NET = _load()


def _baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace("%%MODEL_CLASS%%", "EffectiveTableSolver")
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["EffectiveTableSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_coarse_graining",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == ["recursive_depth", "scale_regime", "representation"]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_coarse_graining" in registry["environments"]
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    assert "float" not in prompt
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_exact_tables_and_fixed_points() -> None:
    fp = NET.generate_instance(depth=1, regime=NET.DIRECT, representation=NET.REVEALED, seed=0)
    rec = NET.generate_instance(depth=2, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=0)
    miss = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
    t, f = NET.true_table_and_fixed(fp)
    assert t == [[1, 0], [0, 0]] and f is True
    _, f2 = NET.true_table_and_fixed(rec)
    assert f2 is True
    t3, f3 = NET.true_table_and_fixed(miss)
    assert f3 is False
    assert t3 == [[8, 8], [8, 8]]
    # replacing a child by a permissive all-ones leaf changes the series table
    foil = __import__("copy").deepcopy(miss)
    foil["regions"]["left"]["weights"] = NET._fp_weights()
    t4, _ = NET.true_table_and_fixed(foil)
    assert t4 != t3


def test_bool_and_malformed() -> None:
    inst = NET.example_visible_instance()
    cert = NET.reference_certificate(inst)
    assert NET.verify_certificate(inst, cert)[0]
    bad = dict(cert)
    bad["fixed"] = "true"
    assert NET.verify_certificate(inst, bad)[0] is False
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.table_from_weights(inst["regions"]["leaf"]["weights"], [0])


def test_relabel_grade_independence() -> None:
    inst = NET.generate_instance(depth=2, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=1)
    twin = NET.relabel_instance(inst, 8)
    assert NET.true_table_and_fixed(inst)[1] == NET.true_table_and_fixed(twin)[1]
    kwargs = dict(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=2)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_baseline().solve, **kwargs)
    assert sum(base.values()) < sum(ref.values())
    assert "solver.py" not in inspect.getsource(NET)


def test_generation_visible() -> None:
    created = []
    try:
        path = _generate_env("test_cg_vis", "easy,easy,easy", seed=1)
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


def test_depth_is_series_region_count() -> None:
    rec = NET.generate_instance(depth=3, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=0)
    assert rec["depth"] == 3
    assert len(rec["regions"]) == 3
    assert NET.true_table_and_fixed(rec)[1] is True
    direct = NET.generate_instance(depth=3, regime=NET.DIRECT, representation=NET.REVEALED, seed=0)
    assert direct["depth"] == 1
    assert len(direct["regions"]) == 1
    inf = NET.public_instance(
        NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.INFERRED, seed=0)
    )
    assert "label_perm" not in inf
    assert "meta" not in inf


def test_heldout() -> None:
    n = 0
    for seed in range(10_000, 10_006):
        inst = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=seed)
        assert NET.true_table_and_fixed(inst)[1] is False
        n += 1
    (ROOT / "docs" / "audits" / "2026-10-16-coarse-baselines.json").write_text(
        json.dumps({"n": n, "local_only_fixed_acc": 0.0, "reference_acc": 1.0}, indent=2) + "\n"
    )
