"""Tests for recursive_holonomy_gluing."""
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
FILES = ROOT / "envs" / "cat_theo" / "recursive_holonomy_gluing" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_holonomy_gluing" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load():
    spec = importlib.util.spec_from_file_location("hol_net", NET_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NET = _load()


def _baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8").replace("%%MODEL_CLASS%%", "FiniteMapSolver")
    ns: dict = {}
    exec(compile(text, "solver.py", "exec"), ns)
    return ns["FiniteMapSolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "generate_env.py"), "--env", "recursive_holonomy_gluing",
         "--name", name, "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_config_prompt_registry() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [a["id"] for a in config["axes"]] == [
        "recursive_depth", "map_family", "cycle_regime", "representation"
    ]
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_holonomy_gluing" in registry["environments"]
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "presheaf", "holonomy", "logarithm", "čech", "cech", "cohomology"):
        assert banned not in prompt
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")


def test_multiplicative_fixed_point_iff_q_one() -> None:
    sat = NET.generate_instance(depth=1, family=NET.MUL, regime=NET.DIRECT, representation=NET.REVEALED, seed=0)
    unsat = NET.generate_instance(depth=2, family=NET.MUL, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0)
    assert NET.composite_of(sat)["q"] % sat["modulus"] == 1
    assert NET.instance_satisfiable(sat) is True
    assert NET.composite_of(unsat)["q"] % unsat["modulus"] != 1
    assert NET.instance_satisfiable(unsat) is False
    assert NET.verify_certificate(sat, NET.reference_certificate(sat))[0]
    assert NET.verify_certificate(unsat, NET.reference_certificate(unsat))[0]


def test_affine_and_permutation_families() -> None:
    aff_sat = NET.generate_instance(depth=2, family=NET.AFF, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=1)
    aff_unsat = NET.generate_instance(depth=2, family=NET.AFF, regime=NET.REC_COMP, representation=NET.REVEALED, seed=1)
    perm_sat = NET.generate_instance(depth=1, family=NET.PERM, regime=NET.DIRECT, representation=NET.REVEALED, seed=2)
    perm_unsat = NET.generate_instance(depth=2, family=NET.PERM, regime=NET.REC_COMP, representation=NET.REVEALED, seed=2)
    assert NET.instance_satisfiable(aff_sat) is True
    assert NET.instance_satisfiable(aff_unsat) is False
    assert NET.instance_satisfiable(perm_sat) is True
    assert NET.instance_satisfiable(perm_unsat) is False


def test_compose_matches_enumeration() -> None:
    for family in (NET.MUL, NET.AFF, NET.PERM):
        inst = NET.generate_instance(depth=2, family=family, regime=NET.RECURSIVE, representation=NET.REVEALED, seed=3)
        spec = NET.composite_of(inst)
        fps = NET.fixed_states(family, spec, inst["domain"], inst["modulus"])
        assert bool(fps) is NET.instance_satisfiable(inst)


def test_relabel_preserves_sat() -> None:
    inst = NET.generate_instance(depth=2, family=NET.AFF, regime=NET.REC_COMP, representation=NET.REVEALED, seed=4)
    twin = NET.relabel_instance(inst, 11)
    assert NET.instance_satisfiable(inst) is NET.instance_satisfiable(twin)
    assert NET.verify_certificate(twin, NET.reference_certificate(twin))[0]


def test_inferred_requires_maps_matching_calibration() -> None:
    inst = NET.generate_instance(depth=1, family=NET.MUL, regime=NET.DIRECT, representation=NET.INFERRED, seed=5)
    cert = NET.reference_certificate(inst)
    assert NET.verify_certificate(inst, cert)[0]
    bad = {"status": "sat", "state": cert["state"]}
    assert NET.verify_certificate(inst, bad)[0] is False


def test_malformed_and_budget() -> None:
    inst = NET.example_visible_instance()
    assert NET.verify_certificate(inst, None)[0] is False
    assert NET.verify_certificate(inst, {"status": "sat"})[0] is False
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.instance_satisfiable(inst, budget=0)


def test_grade_reference_beats_baseline() -> None:
    kwargs = dict(depth=2, family=NET.MUL, regime=NET.REC_COMP, representation=NET.REVEALED, seed=6)
    ref = NET.grade_solver(NET.arm_reference, **kwargs)
    assert all(ref.values()), ref
    base = NET.grade_solver(_baseline().solve, **kwargs)
    assert not base["local_visible"]  # The stub omits the mandatory transport certificate.
    assert sum(base.values()) < sum(ref.values())


def test_path_consistency_is_observed_and_mandatory() -> None:
    inst = NET.generate_instance(
        depth=2, family=NET.AFF, regime=NET.REC_COMP,
        representation=NET.REVEALED, seed=6
    )
    assert NET.paths_agree(inst) is False
    reference = NET.reference_certificate(inst)
    assert reference["path_consistent"] is False
    assert NET.verify_certificate(inst, reference)[0]
    wrong = dict(reference)
    wrong["path_consistent"] = True
    assert NET.verify_certificate(inst, wrong)[0] is False


def test_oracle_not_candidate_solver() -> None:
    assert "solver.py" not in inspect.getsource(NET)
    assert NET.evaluate_solver(lambda _i: {"status": "unsat"}, NET.example_visible_instance()) is False


def test_generation_and_visible_and_prompt_lint() -> None:
    created = []
    try:
        path = _generate_env("test_hol_vis", "easy,easy,easy,easy", seed=1)
        created.append(path)
        blob = "\n".join(p.read_text(errors="ignore") for p in path.rglob("*") if p.is_file())
        assert not re.findall(r"%%[A-Z0-9_]+%%", blob)
        prompt = (path / "agent" / "workspace" / "prompt.md").read_text(encoding="utf-8").lower()
        for banned in ("sheaf", "holonomy", "logarithm", "čech"):
            assert banned not in prompt
        proc = subprocess.run(
            [sys.executable, str(path / "agent" / "workspace" / "visible_tests.py")],
            cwd=path / "agent" / "workspace", text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)


def test_depth_recorded_equals_cycle_leaf_count() -> None:
    for depth in (1, 2, 3):
        inst = NET.generate_instance(
            depth=depth, family=NET.MUL, regime=NET.REC_COMP, representation=NET.REVEALED, seed=0
        )
        assert inst["depth"] == depth
        assert inst["cycle"].count("leaf") == depth
        pub = NET.public_instance(inst)
        assert pub["depth"] == depth
        assert "meta" not in pub
        inf = NET.generate_instance(
            depth=depth, family=NET.MUL, regime=NET.REC_COMP, representation=NET.INFERRED, seed=0
        )
        pub_i = NET.public_instance(inf)
        assert "maps" not in pub_i
        assert "expanded" not in pub_i
        assert "meta" not in pub_i


@pytest.mark.parametrize("seed", tuple(range(10_000, 10_012)))
def test_heldout_baselines_rejected(seed):
    inst = NET.generate_instance(
        depth=2, family=NET.MUL, regime=NET.REC_COMP, representation=NET.REVEALED, seed=seed
    )
    assert not NET.instance_satisfiable(inst)
    assert NET.verify_certificate(inst, NET.reference_certificate(inst))[0]
    assert not NET.verify_certificate(inst, NET.arm_local_only(inst))[0]

@pytest.mark.parametrize("family", (NET.MUL, NET.AFF, NET.PERM))
def test_structural_direct_transport_rival_and_public_calibration(family):
    inst = NET.generate_instance(depth=3, family=family, regime=NET.REC_COMP,
                                 representation=NET.INFERRED, seed=41)
    cert = NET.TransportGraph().direct_certificate(NET.public_instance(inst))
    assert NET.verify_certificate(inst, cert)[0]
    assert cert["status"] == NET.reference_certificate(inst)["status"]
    assert not cert["sections"]


def test_structural_curved_transport_can_have_a_global_section():
    inst = NET.TransportGraph().curved_section(41)
    cert = NET.reference_certificate(inst)
    assert cert["status"] == "sat"
    assert cert["sections"] == (0,)
    assert not cert["path_consistent"]
    assert cert["transport"][2] == "curved"
    assert NET.verify_certificate(inst, cert)[0]
    a, b, geometry = cert["transport"]
    cert["transport"] = (a[::-1], b[::-1], geometry)
    assert NET.verify_certificate(inst, cert)[0]
    cert["transport"] = (a, b, "flat")
    assert not NET.verify_certificate(inst, cert)[0]


def test_structural_second_loop_and_complete_section_set_are_mandatory():
    inst = NET.TransportGraph().curved_section(41)
    inst["maps"]["node_alt"] = {"a": 3, "b": 1}
    inst["calibration"]["node_alt"] = ((0, 1), (1, 4))
    cert = NET.reference_certificate(inst)
    assert cert["status"] == "unsat"
    assert NET.verify_certificate(inst, cert)[0]
    cert["status"] = "sat"
    cert["state"] = 0
    cert["sections"] = (0,)
    assert not NET.verify_certificate(inst, cert)[0]


def test_structural_equal_nonidentity_paths_are_not_flat():
    inst = NET.generate_instance(depth=2, family=NET.AFF, regime=NET.RECURSIVE,
                                 representation=NET.REVEALED, seed=41)
    cert = NET.reference_certificate(inst)
    assert cert["path_consistent"]
    assert cert["transport"][2] == "curved"
    assert cert["sections"]


@pytest.mark.parametrize("rows", (None, ((0,),), ((0, 0),) * 2000))
def test_structural_malformed_transport_is_rejected(rows):
    inst = NET.TransportGraph().curved_section(41)
    cert = NET.reference_certificate(inst)
    a, b, geometry = cert["transport"]
    cert["transport"] = (rows, b, geometry)
    assert not NET.verify_certificate(inst, cert)[0]
