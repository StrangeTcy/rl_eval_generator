"""Tests for recursive_epistemic_gluing."""
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
FILES = ROOT / "envs" / "cat_theo" / "recursive_epistemic_gluing" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_epistemic_gluing" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load_network():
    spec = importlib.util.spec_from_file_location("epi_net", NET_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NET = _load_network()


def _load_baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace(
        "%%MODEL_CLASS%%", "NestedEpistemicSolver"
    )
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["NestedEpistemicSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_epistemic_gluing",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_and_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == [
        "recursive_depth", "gluing_regime", "formula_order", "label_opacity"
    ]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_epistemic_gluing" in registry["environments"]
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "presheaf", "holonomy", "čech", "cech", "cohomology"):
        assert banned not in prompt
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_actual_p_but_ann_does_not_know_p() -> None:
    model = NET.generate_model(depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, order=0, seed=0)
    assert NET.query_value(model) is True
    know = NET.generate_model(depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, order=1, seed=0)
    assert NET.query_value(know) is False
    assert NET.cross_check_flat(model) and NET.cross_check_flat(know)


def test_truncating_depth_changes_nested_query() -> None:
    shallow = NET.generate_model(depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, order=2, seed=0)
    deep = NET.generate_model(depth=2, regime=NET.TREE, opacity=NET.TRANSPARENT, order=2, seed=0)
    # depth-1 has no q; nested K about q is false. depth-2 evaluates q on the inner frame.
    assert "q" not in shallow["frames"][shallow["levels"][0]]["atoms"]
    assert "q" in deep["frames"]["inner"]["atoms"]
    assert NET.cross_check_flat(deep) is True


def test_bundle_obstruction() -> None:
    sat = NET.generate_model(depth=1, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, order=0, seed=1)
    unsat = NET.generate_model(depth=1, regime=NET.CYCLIC_UNSAT, opacity=NET.TRANSPARENT, order=0, seed=1)
    assert NET.bundle_possible(sat) is True
    assert NET.bundle_possible(unsat) is False
    assert NET.query_value(sat) is True  # p still holds at actual


def test_relabel_preserves_answers() -> None:
    model = NET.generate_model(depth=2, regime=NET.CYCLIC_UNSAT, opacity=NET.TRANSPARENT, order=1, seed=4)
    twin = NET.relabel_model(model, seed=11)
    assert NET.reference_certificate(model)["query_value"] == NET.reference_certificate(twin)["query_value"]
    assert NET.reference_certificate(model)["bundle_possible"] == NET.reference_certificate(twin)["bundle_possible"]
    assert model["frames"]["outer"]["worlds"] != twin["frames"]["outer"]["worlds"]


def test_timeout_is_not_unsat() -> None:
    model = NET.example_visible_model()
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.eval_formula(model, model["query"], tuple(model["actual"]), [0])
    assert NET.query_value(model) is True


def test_grade_reference_beats_baseline() -> None:
    kwargs = dict(depth=2, regime=NET.CYCLIC_UNSAT, opacity=NET.OPAQUE, order=2, seed=5)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_load_baseline().solve, **kwargs)
    foil = NET.grade_solver(NET.arm_actual_facts, **kwargs)
    assert base["local_visible"] is True
    assert foil["local_visible"] is True
    assert sum(base.values()) < sum(ref.values())


def test_oracle_independent() -> None:
    assert "solver.py" not in inspect.getsource(NET)
    assert NET.evaluate_solver(lambda _m: {"query_value": False}, NET.example_visible_model()) is False


def test_generation_and_visible() -> None:
    created = []
    try:
        for diff in ("easy,easy,easy,easy", "hard,hard,hard,hard"):
            path = _generate_env(f"test_epi_{diff.replace(',', '_')}", diff, seed=2)
            created.append(path)
            blob = "\n".join(p.read_text(errors="ignore") for p in path.rglob("*") if p.is_file())
            assert not re.findall(r"%%[A-Z0-9_]+%%", blob)
        vis = _generate_env("test_epi_visible", "easy,easy,easy,easy", seed=1)
        created.append(vis)
        proc = subprocess.run(
            [sys.executable, str(vis / "agent" / "workspace" / "visible_tests.py")],
            cwd=vis / "agent" / "workspace", text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)
