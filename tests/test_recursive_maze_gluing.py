"""Tests for recursive_maze_gluing."""
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
FILES = ROOT / "envs" / "cat_theo" / "recursive_maze_gluing" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_maze_gluing" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load_network():
    spec = importlib.util.spec_from_file_location("maze_net", NET_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NET = _load_network()


def _load_baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace("%%MODEL_CLASS%%", "MazeRouteSolver")
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["MazeRouteSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_maze_gluing",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_and_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == [
        "recursive_depth", "gluing_regime", "label_opacity", "structural_ambiguity"
    ]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_maze_gluing" in registry["environments"]
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "presheaf", "holonomy", "čech", "cech", "cohomology"):
        assert banned not in prompt
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_route_not_a_boundary_pair_and_must_descend() -> None:
    maze = NET.generate_maze(depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=0)
    cert = NET.reference_certificate(maze)
    assert cert["status"] == "sat"
    ops = [s["op"] for s in cert["steps"]]
    assert "descend" in ops and "ascend" in ops
    assert "move" in ops
    ok, _ = NET.replay_route(maze, cert["steps"])
    assert ok


def test_regimes_and_local_tiles_walkable() -> None:
    sat = NET.generate_maze(depth=2, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=1)
    unsat = NET.generate_maze(depth=2, regime=NET.CYCLIC_UNSAT, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=1)
    assert NET.maze_satisfiable(sat) is True
    assert NET.maze_satisfiable(unsat) is False
    for tile in unsat["tiles"].values():
        assert tile["rooms"] and tile["edges"]


def test_decoy_is_a_task_change() -> None:
    clean = NET.generate_maze(depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=2)
    decoy = NET.generate_maze(depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.DECOY, seed=2)
    assert "pit" not in clean["tiles"]
    assert "pit" in decoy["tiles"]
    cert = NET.reference_certificate(decoy)
    assert any(s.get("child") == "crypt" for s in cert["steps"] if s["op"] == "descend")


def test_relabel_preserves_sat() -> None:
    maze = NET.generate_maze(depth=2, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=3)
    twin = NET.relabel_maze(maze, seed=9)
    assert NET.maze_satisfiable(maze) is True
    assert NET.maze_satisfiable(twin) is True
    assert maze["tiles"]["keep"]["rooms"] != twin["tiles"]["keep"]["rooms"]


def test_timeout_is_not_unsat() -> None:
    maze = NET.example_visible_maze()
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.shortest_route(maze, max_nodes=1)
    assert NET.maze_satisfiable(maze) is True


def test_grade_reference_beats_baseline() -> None:
    kwargs = dict(depth=2, regime=NET.CYCLIC_UNSAT, opacity=NET.OPAQUE, ambiguity=NET.DECOY, seed=4)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_load_baseline().solve, **kwargs)
    foil = NET.grade_solver(NET.arm_ignore_orientation, **kwargs)
    assert base["local_visible"] is True
    assert foil["assembled_unsat"] is False
    assert sum(base.values()) < sum(ref.values())


def test_oracle_independent() -> None:
    assert "solver.py" not in inspect.getsource(NET)
    assert NET.evaluate_solver(lambda _m: {"status": "unsat"}, NET.example_visible_maze()) is False


def test_generation_and_visible() -> None:
    created = []
    try:
        for diff in ("easy,easy,easy,easy", "hard,hard,hard,hard"):
            path = _generate_env(f"test_maze_{diff.replace(',', '_')}", diff, seed=2)
            created.append(path)
            blob = "\n".join(p.read_text(errors="ignore") for p in path.rglob("*") if p.is_file())
            assert not re.findall(r"%%[A-Z0-9_]+%%", blob)
        vis = _generate_env("test_maze_visible", "easy,easy,easy,easy", seed=1)
        created.append(vis)
        proc = subprocess.run(
            [sys.executable, str(vis / "agent" / "workspace" / "visible_tests.py")],
            cwd=vis / "agent" / "workspace", text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)
