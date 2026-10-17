"""Tests for recursive_compiler_bootstrap."""
from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "envs" / "cat_theo" / "recursive_compiler_bootstrap" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_compiler_bootstrap" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load():
    spec = importlib.util.spec_from_file_location("cmp_net", NET_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NET = _load()


def _baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace("%%MODEL_CLASS%%", "BootstrapSolver")
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["BootstrapSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_compiler_bootstrap",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == ["recursive_depth", "bootstrap_regime", "representation"]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_compiler_bootstrap" in registry["environments"]
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "holonomy", "paradox"):
        assert banned not in prompt
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_interpreters_and_local_vs_path() -> None:
    sat = NET.generate_instance(depth=2, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=0)
    unsat = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
    assert NET.stage_locally_ok(sat) and NET.stage_locally_ok(unsat)
    assert NET.claim_holds(sat) is True
    assert NET.claim_holds(unsat) is False
    assert NET.eval_source(["add", 1, 2], 5, [100]) == 3
    ops = NET.finalize(NET.compile_source(["add", 1, 2]))
    assert NET.eval_bytecode(ops, 5, [100]) == 3


def test_bool_type_and_malformed() -> None:
    inst = NET.example_visible_instance()
    assert NET.verify_certificate(inst, {"equivalent": "true"})[0] is False
    assert NET.verify_certificate(inst, {"equivalent": 1})[0] is False
    assert NET.verify_certificate(inst, NET.reference_certificate(inst))[0]


def test_relabel_and_grade() -> None:
    inst = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=2)
    twin = NET.relabel_instance(inst, 9)
    assert NET.claim_holds(inst) is NET.claim_holds(twin) is False
    kwargs = dict(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=3)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_baseline().solve, **kwargs)
    assert sum(base.values()) < sum(ref.values())


def test_oracle_not_candidate_solver() -> None:
    assert "solver.py" not in inspect.getsource(NET)
    assert NET.evaluate_solver(lambda _i: {"equivalent": False}, NET.example_visible_instance()) is False


def test_generation_visible_prompt() -> None:
    created = []
    try:
        path = _generate_env("test_cmp_vis", "easy,easy,easy", seed=1)
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


def test_programs_sampled_from_bounded_grammar() -> None:
    pool = {json.dumps(p) for p in NET.grammar_pool(2)}
    seen: list[list] = []
    for seed in range(8):
        inst = NET.generate_instance(depth=2, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=seed)
        assert inst["depth"] == inst["program_height"] == 2
        assert len(inst["programs"]) == NET.PROGRAM_SAMPLE
        assert all(json.dumps(p) in pool for p in inst["programs"])
        seen.append(inst["programs"])
    assert any(seen[0] != other for other in seen[1:])
    capped = NET.generate_instance(depth=3, regime=NET.REC_COMP, representation=NET.INFERRED, seed=0)
    assert capped["depth"] == capped["program_height"] == 2
    pub = NET.public_instance(capped)
    assert "encodings" not in pub
    assert "meta" not in pub
    assert all("perm" not in st for st in pub["stages"])
    rev = NET.public_instance(
        NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
    )
    assert "encodings" in rev


def test_heldout_local_baseline_misses_path_obstruction() -> None:
    rows = []
    for seed in range(10_000, 10_008):
        inst = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=seed)
        rows.append((NET.claim_holds(inst), NET.arm_local_only(inst)["equivalent"]))
    assert all(t is False for t, _ in rows)
    assert all(p is True for _, p in rows)
    (ROOT / "docs" / "audits" / "2026-10-16-compiler-baselines.json").write_text(
        json.dumps({"n": len(rows), "local_only_unsat_acc": 0.0, "reference_acc": 1.0}, indent=2) + "\n"
    )
