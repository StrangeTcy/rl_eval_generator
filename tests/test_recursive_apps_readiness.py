"""Leakage, depth honesty, shortcut, and control regressions for the four apps.

Passing these tests is generator/oracle correctness and shortcut resistance.
It is not a model-performance result and does not make the suite a validated
benchmark.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]

AGENT_BANNED = (
    "sheaf",
    "presheaf",
    "holonomy",
    "logarithm",
    "čech",
    "cech",
    "cohomology",
    "monodromy",
    "local system",
    "gluing",
    "glueing",
    "recursive_composition",
    "sat_twist",
    "intended algorithm",
    "fixed point",
)

NEVER_PUBLIC_KEYS = {"meta", "composite", "expect_fixed", "sat"}
HIDDEN_WHEN_INFERRED = {"maps", "expanded", "encodings", "perms", "label_perm"}


def _load(env: str, mod_name: str):
    path = ROOT / "envs" / "cat_theo" / env / "files" / "network.py"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HOL = _load("recursive_holonomy_gluing", "hol_ready")
CMP = _load("recursive_compiler_bootstrap", "cmp_ready")
COD = _load("recursive_error_correcting_codes", "cod_ready")
CRS = _load("recursive_coarse_graining", "crs_ready")


def _keys(obj: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(obj, dict):
        found.update(obj)
        for value in obj.values():
            found |= _keys(value)
    elif isinstance(obj, list):
        for value in obj:
            found |= _keys(value)
    return found


def _assert_public_clean(pub: dict[str, Any], *, revealed: bool) -> None:
    keys = _keys(pub)
    leaked = keys & NEVER_PUBLIC_KEYS
    assert not leaked, leaked
    if not revealed:
        leaked_h = keys & HIDDEN_WHEN_INFERRED
        assert not leaked_h, leaked_h
        for stage in pub.get("stages") or []:
            if isinstance(stage, dict):
                assert "perm" not in stage


def _generate_env(env: str, name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "generate_env.py"),
            "--env",
            env,
            "--name",
            name,
            "--difficulty",
            difficulty,
            "--seed",
            str(seed),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return target


def test_holonomy_public_payload_strips_secrets() -> None:
    for representation in (HOL.REVEALED, HOL.INFERRED):
        for regime in (HOL.DIRECT, HOL.RECURSIVE, HOL.FLAT, HOL.REC_COMP):
            inst = HOL.generate_instance(
                depth=2, family=HOL.MUL, regime=regime, representation=representation, seed=0
            )
            pub = HOL.public_instance(inst)
            _assert_public_clean(pub, revealed=representation == HOL.REVEALED)
            payload = json.dumps([{"name": "configured", "instance": pub}])
            assert '"meta"' not in payload
            assert "recursive_composition" not in payload


def test_compiler_public_payload_strips_secrets() -> None:
    for representation in (CMP.REVEALED, CMP.INFERRED):
        for regime in (CMP.DIRECT, CMP.RECURSIVE, CMP.FLAT, CMP.REC_COMP):
            inst = CMP.generate_instance(
                depth=2, regime=regime, representation=representation, seed=0
            )
            pub = CMP.public_instance(inst)
            _assert_public_clean(pub, revealed=representation == CMP.REVEALED)
            assert "recursive_composition" not in json.dumps(pub)


def test_codes_public_payload_strips_secrets() -> None:
    for representation in (COD.REVEALED, COD.INFERRED):
        for regime in (COD.DIRECT, COD.RECURSIVE, COD.FLAT, COD.REC_COMP):
            inst = COD.generate_instance(
                depth=2, regime=regime, representation=representation, seed=0
            )
            pub = COD.public_instance(inst)
            _assert_public_clean(pub, revealed=representation == COD.REVEALED)


def test_coarse_public_payload_strips_secrets() -> None:
    for representation in (CRS.REVEALED, CRS.INFERRED):
        for regime in (CRS.DIRECT, CRS.RECURSIVE, CRS.FLAT, CRS.REC_COMP):
            inst = CRS.generate_instance(
                depth=2, regime=regime, representation=representation, seed=0
            )
            pub = CRS.public_instance(inst)
            _assert_public_clean(pub, revealed=representation == CRS.REVEALED)


@pytest.mark.parametrize(
    "env,difficulty,folder",
    [
        ("recursive_holonomy_gluing", "easy,easy,easy,easy", "test_ready_hol"),
        ("recursive_compiler_bootstrap", "easy,easy,easy", "test_ready_cmp"),
        ("recursive_error_correcting_codes", "easy,easy,easy", "test_ready_cod"),
        ("recursive_coarse_graining", "easy,easy,easy", "test_ready_crs"),
    ],
)
def test_agent_workspace_has_no_theory_leaks(env: str, difficulty: str, folder: str) -> None:
    path = _generate_env(env, folder, difficulty, seed=1)
    try:
        workspace = path / "agent" / "workspace"
        assert workspace.is_dir()
        assert not (workspace / "generation.json").exists()
        blob = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in workspace.rglob("*")
            if p.is_file()
        ).lower()
        assert not re.findall(r"%%[A-Z0-9_]+%%", blob)
        for banned in AGENT_BANNED:
            assert banned not in blob, banned
        assert env not in blob
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_shortcut_zero_reference_one_on_d_class() -> None:
    hol = HOL.generate_instance(
        depth=2, family=HOL.MUL, regime=HOL.REC_COMP, representation=HOL.REVEALED, seed=10_000
    )
    assert HOL.instance_satisfiable(hol) is False
    assert HOL.arm_local_only(hol)["status"] == "sat"
    assert HOL.arm_reference(hol)["status"] == "unsat"
    assert HOL.evaluate_solver(HOL.arm_reference, hol) is True
    assert HOL.evaluate_solver(HOL.arm_local_only, hol) is False

    cmp = CMP.generate_instance(depth=2, regime=CMP.REC_COMP, representation=CMP.REVEALED, seed=10_000)
    assert CMP.claim_holds(cmp) is False
    assert CMP.arm_local_only(cmp)["equivalent"] is True
    assert CMP.arm_reference(cmp)["equivalent"] is False
    assert CMP.evaluate_solver(CMP.arm_reference, cmp) is True
    assert CMP.evaluate_solver(CMP.arm_local_only, cmp) is False

    cod = COD.generate_instance(depth=2, regime=COD.REC_COMP, representation=COD.REVEALED, seed=10_000)
    assert COD.stacked_satisfiable(cod) is False
    assert COD.local_kernels_nonempty(cod) is True
    assert COD.arm_local_only(cod)["status"] == "sat"
    assert COD.arm_reference(cod)["status"] == "unsat"
    assert COD.evaluate_solver(COD.arm_reference, cod) is True
    assert COD.evaluate_solver(COD.arm_local_only, cod) is False

    crs = CRS.generate_instance(depth=2, regime=CRS.REC_COMP, representation=CRS.REVEALED, seed=10_000)
    assert CRS.true_table_and_fixed(crs)[1] is False
    assert CRS.arm_local_only(crs)["fixed"] is True
    assert CRS.arm_reference(crs)["fixed"] is False
    assert CRS.evaluate_solver(CRS.arm_reference, crs) is True
    assert CRS.evaluate_solver(CRS.arm_local_only, crs) is False


def test_isomorphic_rename_preserves_structural_change_flips() -> None:
    hol = HOL.generate_instance(
        depth=2, family=HOL.AFF, regime=HOL.REC_COMP, representation=HOL.REVEALED, seed=4
    )
    twin = HOL.relabel_instance(hol, 11)
    assert HOL.instance_satisfiable(hol) is HOL.instance_satisfiable(twin) is False
    flipped = __import__("copy").deepcopy(hol)
    flipped["maps"]["node_extra"] = {"a": 1, "b": 0}
    flipped["expanded"] = [__import__("copy").deepcopy(flipped["maps"][n]) for n in flipped["cycle"]]
    assert HOL.instance_satisfiable(flipped) is True

    cmp = CMP.generate_instance(depth=2, regime=CMP.REC_COMP, representation=CMP.REVEALED, seed=2)
    twin_c = CMP.relabel_instance(cmp, 9)
    assert CMP.claim_holds(cmp) is CMP.claim_holds(twin_c) is False
    repaired = __import__("copy").deepcopy(cmp)
    last = repaired["stages"][-1]["name"]
    repaired["claimed_decoder"] = CMP.invert_encoding(repaired["encodings"][last])
    assert CMP.claim_holds(repaired) is True

    cod = COD.generate_instance(depth=2, regime=COD.REC_COMP, representation=COD.REVEALED, seed=0)
    assert COD.stacked_satisfiable(cod) is False
    sat_parent = __import__("copy").deepcopy(cod)
    sat_parent["parent_check"]["rhs"] = 0
    assert COD.stacked_satisfiable(sat_parent) is True

    crs = CRS.generate_instance(depth=2, regime=CRS.REC_COMP, representation=CRS.REVEALED, seed=0)
    twin_r = CRS.relabel_instance(crs, 8)
    assert CRS.true_table_and_fixed(crs)[1] is CRS.true_table_and_fixed(twin_r)[1] is False
    repaired_r = __import__("copy").deepcopy(crs)
    for name in repaired_r["regions"]:
        repaired_r["regions"][name]["weights"] = CRS._fp_weights()
    assert CRS.true_table_and_fixed(repaired_r)[1] is True


def test_regime_polarity_is_not_a_depth_label() -> None:
    """SAT/UNSAT is the regime, not a relabel of the same structure as 'harder'."""
    hol_d1 = HOL.generate_instance(
        depth=1, family=HOL.MUL, regime=HOL.REC_COMP, representation=HOL.REVEALED, seed=0
    )
    hol_d2 = HOL.generate_instance(
        depth=2, family=HOL.MUL, regime=HOL.REC_COMP, representation=HOL.REVEALED, seed=0
    )
    hol_rec = HOL.generate_instance(
        depth=2, family=HOL.MUL, regime=HOL.RECURSIVE, representation=HOL.REVEALED, seed=0
    )
    assert hol_d1["depth"] == 1 and hol_d2["depth"] == 2
    assert len(hol_d1["cycle"]) != len(hol_d2["cycle"])
    assert HOL.instance_satisfiable(hol_d1) is HOL.instance_satisfiable(hol_d2) is False
    assert HOL.instance_satisfiable(hol_rec) is True

    cod_d1 = COD.generate_instance(depth=1, regime=COD.REC_COMP, representation=COD.REVEALED, seed=0)
    cod_d3 = COD.generate_instance(depth=3, regime=COD.REC_COMP, representation=COD.REVEALED, seed=0)
    assert len(cod_d1["blocks"]) == 1 and len(cod_d3["blocks"]) == 3
    assert COD.stacked_satisfiable(cod_d1) is COD.stacked_satisfiable(cod_d3) is False
    assert COD.stacked_satisfiable(
        COD.generate_instance(depth=3, regime=COD.RECURSIVE, representation=COD.REVEALED, seed=0)
    ) is True

    crs_d2 = CRS.generate_instance(depth=2, regime=CRS.RECURSIVE, representation=CRS.REVEALED, seed=0)
    crs_d3 = CRS.generate_instance(depth=3, regime=CRS.RECURSIVE, representation=CRS.REVEALED, seed=0)
    assert crs_d2["depth"] == 2 and crs_d3["depth"] == 3
    assert CRS.true_table_and_fixed(crs_d2)[1] is CRS.true_table_and_fixed(crs_d3)[1] is True
