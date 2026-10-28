"""Tests for recursive_compiler_bootstrap."""
from __future__ import annotations

import pytest

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
    assert not NET.evaluate_solver(lambda _i: {"equivalent": False}, NET.example_visible_instance())


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
    assert capped["depth"] == capped["program_height"] == 3
    pub = NET.public_instance(capped)
    assert "encodings" not in pub
    assert "meta" not in pub
    assert all("perm" not in st for st in pub["stages"])
    rev = NET.public_instance(
        NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
    )
    assert "encodings" in rev


@pytest.mark.parametrize("seed", tuple(range(10_000, 10_008)))
def test_heldout_local_baseline_misses_path_obstruction(seed):
    inst = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=seed)
    assert not NET.claim_holds(inst)
    assert NET.verify_certificate(inst, NET.reference_certificate(inst))[0]
    assert not NET.verify_certificate(inst, NET.arm_local_only(inst))[0]

@pytest.mark.parametrize("shift", (0, 5, 16))
def test_structural_l1_compiler_compiles_itself(shift):
    machine = NET.BootstrapMachine()
    seed = machine.seed(NET.COMPILER_SOURCE, shift)
    rebuilt = machine.run(seed, (NET.COMPILER_SOURCE, shift), shift)
    assert rebuilt == seed
    assert machine.semantics(rebuilt, shift, machine.challenges(2, 43))


def test_structural_bootstrap_json_and_alternative_source():
    inst = NET.generate_instance(depth=1, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=41)
    public = NET.public_instance(inst)
    assert public["bootstrap"][3] is None
    cert = NET.reference_certificate(public)
    assert NET.verify_certificate(inst, json.loads(json.dumps(cert)))[0]
    task = inst["bootstrap"]
    alternative = (13, (1,), NET.COMPILER_SOURCE)
    machine = NET.BootstrapMachine()
    chain = machine.stages(alternative, task[4], task[1], task[2])
    assert machine.verify(task, (alternative, chain))
    assert not machine.verify(task, (alternative, (task[4],) * task[1]))
    assert machine.semantic_valid(task, (alternative, (task[4],) * task[1]))
    assert not machine.chain_valid(task, (alternative, (task[4],) * task[1]))
    assert not machine.verify(task, (None, (task[4],) * task[1]))


def test_structural_bootstrap_rejects_corruption_and_truncation():
    task = NET.example_visible_instance()["bootstrap"]
    machine = NET.BootstrapMachine()
    source, stages = machine.certificate(task)
    assert not machine.verify(task, (source, stages[:-1]))
    assert not machine.verify(task, (source, stages + (stages[-1],)))
    assert not machine.verify(task, ((12,), stages))
    assert not NET.BootstrapMachine(fuel=1).verify(task, (source, stages))


def test_structural_invalid_source_is_not_a_compiler_counterexample():
    inst = NET.generate_instance(depth=1, regime=NET.REC_COMP, representation=NET.REVEALED, seed=41)
    cert = NET.reference_certificate(inst)
    cert["counterexample"] = {"source": ["invalid"], "source_value": 0, "decoded_value": None}
    assert not NET.verify_certificate(inst, cert)[0]


def test_structural_depth_does_real_work_or_fails_explicitly():
    a = NET.generate_instance(depth=2, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=41)
    b = NET.generate_instance(depth=4, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=41)
    assert a["bootstrap"][1] == 3
    assert b["bootstrap"][1] == 5
    assert b["program_height"] == 4
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.generate_instance(depth=5, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=41)
