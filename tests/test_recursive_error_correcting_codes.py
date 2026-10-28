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


def test_depth_is_block_count() -> None:
    for depth in (1, 2, 3):
        inst = NET.generate_instance(depth=depth, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
        assert inst["depth"] == depth
        assert len(inst["blocks"]) == depth
        pub = NET.public_instance(inst)
        assert pub["depth"] == depth
        assert "meta" not in pub
        inf = NET.generate_instance(depth=depth, regime=NET.REC_COMP, representation=NET.INFERRED, seed=0)
        pub_i = NET.public_instance(inf)
        assert "perms" not in pub_i
    assert "meta" not in pub_i


def test_inferred_presentation_is_identifiable_from_calibration() -> None:
    inst = NET.generate_instance(
        depth=2, regime=NET.REC_COMP, representation=NET.INFERRED, seed=3
    )
    public = NET.public_instance(inst)
    assert "perms" not in public
    cert = NET.reference_certificate(inst)
    assert "perms" in cert
    assert NET.verify_certificate(inst, cert)[0]
    wrong = dict(cert)
    wrong["perms"] = {name: [0, 1] for name in inst["blocks"]}
    assert NET.verify_certificate(inst, wrong)[0] is False


@pytest.mark.parametrize("seed", tuple(range(10_000, 10_006)))
def test_heldout(seed):
    inst = NET.generate_instance(depth=2, regime=NET.REC_COMP, representation=NET.REVEALED, seed=seed)
    assert not NET.stacked_satisfiable(inst)
    assert NET.verify_certificate(inst, NET.reference_certificate(inst))[0]
    assert not NET.verify_certificate(inst, NET.arm_local_only(inst))[0]

@pytest.mark.parametrize("depth,blocked", ((1, 0), (2, 1), (3, 0), (3, 1)))
def test_structural_elimination_agrees_with_exhaustive_rival(depth, blocked):
    inst = NET.CodePresentation().parent_control(depth, NET.INFERRED, 41, blocked)
    linear = NET.reference_certificate(NET.public_instance(inst))
    exhaustive = NET.enumeration_certificate(inst)
    assert linear["status"] == exhaustive["status"]
    assert (linear["status"] == "sat") == NET.stacked_satisfiable(inst)
    assert NET.verify_certificate(inst, linear)[0]
    assert NET.verify_certificate(inst, exhaustive)[0]


def test_structural_linear_solver_extends_past_enumeration_budget():
    inst = NET.CodePresentation().parent_control(8, NET.REVEALED, 41, 1)
    assert NET.reference_certificate(inst)["status"] == "unsat"
    assert NET.verify_certificate(inst, NET.reference_certificate(inst))[0]
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.stacked_satisfiable(inst, budget=10)


def test_structural_calibration_ambiguity_and_distinguishing_probe():
    probe = NET.CodePresentation()
    ambiguous = probe.identification(41)
    identified = probe.identification(41, 1)
    a, syndrome, corrections = probe.invariants(ambiguous)
    b, _, _ = probe.invariants(identified)
    assert probe.width(a) == 2
    assert probe.width(b) == 1
    assert set(b).issubset(a)
    assert probe.verify(ambiguous, (a, syndrome, corrections))
    assert not probe.verify(ambiguous, (a[:1], syndrome, corrections))


def test_structural_coordinate_twin_changes_math_and_preserves_verdict():
    inst = NET.CodePresentation().parent_control(3, NET.INFERRED, 41, 1)
    twin = NET.relabel_instance(inst, 97)
    assert inst["blocks"] != twin["blocks"]
    assert inst["calibration"] != twin["calibration"]
    assert NET.reference_certificate(inst)["status"] == NET.reference_certificate(twin)["status"]
    assert NET.verify_certificate(twin, NET.reference_certificate(NET.public_instance(twin)))[0]


def test_structural_codeword_shape_and_field_domain_are_mandatory():
    inst = NET.example_visible_instance()
    cert = NET.reference_certificate(inst)
    cert["blocks"]["A"] = (0,)
    assert not NET.verify_certificate(inst, cert)[0]
    cert["blocks"]["A"] = (0, 0, 0)
    assert not NET.verify_certificate(inst, cert)[0]
    cert["blocks"]["A"] = (0.5, 0)
    assert not NET.verify_certificate(inst, cert)[0]
