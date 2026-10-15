"""Tests for recursive_gluing_discovery: v0's research sibling.

v0 remains the fully-observed CSP control. These tests check that the
public view withholds complete tables, that three offline solver arms
separate generic search from latent-given and discovery solvers, and
that each axis changes the intended property.
"""
from __future__ import annotations

import importlib.util
import inspect
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FILES = ROOT / "envs" / "cat_theo" / "recursive_gluing_discovery" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_gluing_discovery" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load_network():
    spec = importlib.util.spec_from_file_location("rgd_network", NET_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NET = _load_network()


def _load_baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8")
    text = text.replace("%%MODEL_CLASS%%", "ChartAssemblySolver")
    namespace: dict = {}
    exec(compile(text, "solver.py", "exec"), namespace)
    return namespace["ChartAssemblySolver"]()


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "generate_env.py"),
            "--env",
            "recursive_gluing_discovery",
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


def test_config_layout_and_prompt_do_not_name_the_trick() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert [axis["id"] for axis in config["axes"]] == [
        "recursive_depth",
        "state_space",
        "gluing_regime",
        "transport_family",
    ]
    assert config["layout"]["judge/network.py"] == "network.py"
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_gluing" in registry["environments"]
    assert registry["environments"]["recursive_gluing_discovery"].endswith(
        "recursive_gluing_discovery/config.yaml"
    )
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "holonomy", "affine", "group action", "logarithm", "z/n"):
        assert banned not in prompt
    assert "%%" not in NET_PATH.read_text(encoding="utf-8")


def test_public_view_withholds_complete_tables() -> None:
    bundle = NET.generate_bundle(
        depth=3, domain_size=7, regime=NET.CYCLIC_SAT, family=NET.AFFINE, seed=3
    )
    public, complete = bundle["public"], bundle["complete"]
    assert NET.has_unprobed_overlap(public)
    assert NET.listed_pair_count(public) < NET.complete_pair_count(complete)
    assert NET.cartesian_size(complete) > 1_000_000
    assert "cycle" in next(iter(public["regions"].values()))
    assert "cycle" not in next(iter(complete["regions"].values()))
    assert public["copies"]
    assert NET.max_name_depth(complete) == 3
    assert NET.oracle_satisfiable(complete) is True


def test_recursive_depth_and_family_and_regime_move_the_task() -> None:
    shallow = NET.generate_bundle(
        depth=1, domain_size=5, regime=NET.TREE, family=NET.TRANSLATION, seed=0
    )
    deep = NET.generate_bundle(
        depth=3, domain_size=5, regime=NET.TREE, family=NET.TRANSLATION, seed=0
    )
    assert NET.region_count(shallow["complete"]) == 3
    assert NET.region_count(deep["complete"]) == 15
    assert not NET.has_unprobed_overlap(shallow["public"])
    sat = NET.generate_bundle(
        depth=2, domain_size=5, regime=NET.CYCLIC_SAT, family=NET.TRANSLATION, seed=1
    )
    unsat = NET.generate_bundle(
        depth=2, domain_size=5, regime=NET.CYCLIC_UNSAT, family=NET.TRANSLATION, seed=1
    )
    assert NET.oracle_satisfiable(sat["complete"]) is True
    assert NET.oracle_satisfiable(unsat["complete"]) is False
    trans = NET.generate_bundle(
        depth=2, domain_size=7, regime=NET.CYCLIC_SAT, family=NET.TRANSLATION, seed=4
    )
    aff = NET.generate_bundle(
        depth=2, domain_size=7, regime=NET.CYCLIC_SAT, family=NET.AFFINE, seed=4
    )
    assert NET.oracle_satisfiable(trans["complete"]) is True
    assert NET.oracle_satisfiable(aff["complete"]) is True
    # Affine instances are not the translation completion of their probes.
    foil = NET.translation_only_discover(aff["public"])
    parsed, _err = NET.parse_solve_output(aff["complete"], foil)
    assert parsed is None or parsed["status"] != "sat" or not NET.validate_assignment(
        aff["complete"], parsed.get("assignment", {})
    )[0]


def test_three_arms_separate_generic_from_discovery() -> None:
    bundle = NET.generate_bundle(
        depth=2, domain_size=7, regime=NET.CYCLIC_SAT, family=NET.AFFINE, seed=8
    )
    public, complete = bundle["public"], bundle["complete"]
    assert NET.evaluate_against_complete(NET.arm_given_latent, complete, complete) is True
    assert NET.evaluate_against_complete(NET.arm_discover, public, complete) is True
    assert NET.evaluate_against_complete(NET.arm_generic_sparse, public, complete) is False
    given = NET.arm_given_latent(complete)
    discovered = NET.arm_discover(public)
    assert given["status"] == discovered["status"] == "sat"


def test_unsat_assembly_with_locally_fine_copies() -> None:
    bundle = NET.generate_bundle(
        depth=2, domain_size=5, regime=NET.CYCLIC_UNSAT, family=NET.TRANSLATION, seed=2
    )
    complete = bundle["complete"]
    assert NET.oracle_satisfiable(complete) is False
    # Dropping skip/cycle edges (the assembly) leaves a satisfiable tree.
    tree_only = {
        "regions": complete["regions"],
        "overlaps": [
            ov
            for ov in complete["overlaps"]
            if ov["left"].count("/") + 1 == ov["right"].count("/")
        ],
    }
    assert NET.oracle_satisfiable(tree_only) is True
    assert NET.evaluate_against_complete(
        NET.arm_discover, bundle["public"], complete
    ) is True
    assert NET.arm_discover(bundle["public"])["status"] == "unsat"


def test_relabel_preserves_sat_and_withholding() -> None:
    bundle = NET.generate_bundle(
        depth=2, domain_size=5, regime=NET.CYCLIC_SAT, family=NET.TRANSLATION, seed=9
    )
    relabeled = NET.relabel_bundle(bundle, seed=21)
    assert NET.oracle_satisfiable(bundle["complete"]) is True
    assert NET.oracle_satisfiable(relabeled["complete"]) is True
    assert NET.has_unprobed_overlap(relabeled["public"])
    assert NET.evaluate_against_complete(
        NET.arm_discover, relabeled["public"], relabeled["complete"]
    )


def test_grade_reference_vs_baseline_and_generic() -> None:
    kwargs = dict(depth=2, domain_size=5, regime=NET.CYCLIC_UNSAT, family=NET.AFFINE, seed=6)
    ref = NET.grade_solver(NET.arm_discover, **kwargs)
    assert all(ref.values()), ref
    generic = NET.grade_solver(NET.arm_generic_sparse, **kwargs)
    base = NET.grade_solver(_load_baseline().solve, **kwargs)
    assert generic["local_visible"] is True
    assert base["local_visible"] is True
    assert sum(generic.values()) < sum(ref.values())
    assert sum(base.values()) < sum(ref.values())


def test_oracle_independent_of_candidate() -> None:
    source = inspect.getsource(NET)
    assert "solver.py" not in source
    assert "ChartAssemblySolver" not in source
    bundle = NET.generate_bundle(
        depth=1, domain_size=5, regime=NET.TREE, family=NET.TRANSLATION, seed=0
    )
    assert NET.oracle_satisfiable(bundle["complete"]) is True

    def always_unsat(_public):
        return {"status": "unsat"}

    assert NET.evaluate_against_complete(
        always_unsat, bundle["public"], bundle["complete"]
    ) is False


def test_generation_cli(tmp_path: Path) -> None:
    covering = [
        "easy,easy,easy,easy",
        "hard,easy,easy,easy",
        "easy,hard,easy,easy",
        "easy,easy,hard,easy",
        "easy,easy,easy,hard",
        "hard,hard,hard,hard",
    ]
    created = []
    try:
        for difficulty in covering:
            generated = _generate_env(
                f"test_rgd_{difficulty.replace(',', '_')}", difficulty, seed=4
            )
            created.append(generated)
            blob = "\n".join(
                path.read_text(errors="ignore")
                for path in generated.rglob("*")
                if path.is_file()
            )
            assert not re.findall(r"%%[A-Z0-9_]+%%", blob), difficulty
            py_files = [str(path) for path in generated.rglob("*.py")]
            compiled = subprocess.run(
                [sys.executable, "-m", "py_compile", *py_files],
                capture_output=True,
                text=True,
            )
            assert compiled.returncode == 0, compiled.stderr
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)


def test_visible_tests_pass_on_baseline() -> None:
    generated = _generate_env("test_rgd_visible", "easy,easy,easy,easy", seed=1)
    try:
        workspace = generated / "agent" / "workspace"
        proc = subprocess.run(
            [sys.executable, str(workspace / "visible_tests.py")],
            cwd=workspace,
            text=True,
            capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    finally:
        shutil.rmtree(generated, ignore_errors=True)
