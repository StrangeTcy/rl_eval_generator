"""Tests for the recursive_gluing environment family."""
from __future__ import annotations

import importlib.util
import inspect
import itertools
import re
import shutil
import subprocess
import sys
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FILES = ROOT / "envs" / "cat_theo" / "recursive_gluing" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_gluing" / "config.yaml"
NET_PATH = FILES / "network.py"


def _load_network():
    spec = importlib.util.spec_from_file_location("recursive_gluing_network", NET_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NET = _load_network()


def _load_baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8")
    text = text.replace("%%MODEL_CLASS%%", "RegionNetworkSolver")
    namespace: dict = {}
    exec(compile(text, "solver.py", "exec"), namespace)
    return namespace["RegionNetworkSolver"]()


def _baseline_solve(instance):
    return _load_baseline().solve(instance)


def _all_axis_levels():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [list(axis["levels"]) for axis in config["axes"]]


def _level_params(levels: list[str]) -> dict:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    params = {}
    for axis, level in zip(config["axes"], levels, strict=True):
        mapping = axis["levels"][level]
        for key, value in mapping.items():
            name = str(key).strip("%")
            params[name] = str(value)
    return params


def _instance_from_levels(levels: list[str], seed: int = 0):
    params = _level_params(levels)
    return NET.generate_instance(
        depth=int(params["DEPTH"]),
        domain_size=int(params["DOMAIN_SIZE"]),
        regime=params["GLUING_REGIME"],
        label_mode=params["LABEL_MODE"],
        seed=seed,
    )


def _generate_env(name: str, difficulty: str, seed: int = 0) -> Path:
    # generate_env.py refuses paths outside the repo; test_* is gitignored.
    target = ROOT / name
    shutil.rmtree(target, ignore_errors=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "generate_env.py"),
            "--env",
            "recursive_gluing",
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


# ---------------------------------------------------------------------------
# Config and layout
# ---------------------------------------------------------------------------

def test_config_and_file_layout() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    axis_ids = [axis["id"] for axis in config["axes"]]
    assert axis_ids == [
        "recursive_depth",
        "state_space",
        "gluing_regime",
        "label_opacity",
    ]
    assert config["axes"][0]["class"] == "task"
    assert config["axes"][1]["class"] == "task"
    assert config["axes"][2]["class"] == "task"
    assert config["axes"][3]["class"] == "presentation"
    assert config["scoring"]["mode"] == "continuous_accuracy"
    required = [
        FILES / "prompt.md",
        FILES / "solver.py",
        FILES / "visible_tests.py",
        FILES / "judge.py",
        FILES / "network.py",
        CONFIG,
    ]
    for path in required:
        assert path.is_file(), path
    layout = config["layout"]
    assert "judge/network.py" in layout
    assert layout["judge/network.py"] == "network.py"
    assert "agent/workspace/%%MODEL_FILE%%" in layout
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert registry["environments"]["recursive_gluing"] == (
        "envs/cat_theo/recursive_gluing/config.yaml"
    )
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in ("sheaf", "holonomy", "group action", "logarithm", "arc consistency"):
        assert banned not in prompt
    assert "%%" not in NET_PATH.read_text(encoding="utf-8")


def test_generation_for_each_supported_level() -> None:
    covering = [
        "easy,easy,easy,easy",
        "medium,easy,easy,easy",
        "hard,easy,easy,easy",
        "easy,medium,easy,easy",
        "easy,hard,easy,easy",
        "easy,easy,medium,easy",
        "easy,easy,hard,easy",
        "easy,easy,easy,hard",
        "hard,hard,hard,hard",
    ]
    created: list[Path] = []
    try:
        for difficulty in covering:
            generated = _generate_env(
                f"test_rg_levels_{difficulty.replace(',', '_')}", difficulty, seed=4
            )
            created.append(generated)
            assert (generated / "run_eval.sh").is_file()
            assert (generated / "agent" / "workspace" / "solver.py").is_file()
            assert (generated / "judge" / "network.py").is_file()
            assert (generated / "judge" / "judge.py").is_file()
            blob = "\n".join(
                path.read_text(errors="ignore")
                for path in generated.rglob("*")
                if path.is_file()
            )
            unresolved = re.findall(r"%%[A-Z0-9_]+%%", blob)
            assert not unresolved, (difficulty, set(unresolved))
            py_files = [str(path) for path in generated.rglob("*.py")]
            compiled = subprocess.run(
                [sys.executable, "-m", "py_compile", *py_files],
                capture_output=True,
                text=True,
            )
            assert compiled.returncode == 0, compiled.stderr
            judge_text = (generated / "judge" / "judge.py").read_text(encoding="utf-8")
            assert "%%" not in judge_text
            assert "RegionNetworkSolver" in judge_text
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)


def test_cli_generation_is_deterministic() -> None:
    first = _generate_env("test_rg_det_a", "hard,medium,hard,hard", seed=9)
    second = _generate_env("test_rg_det_b", "hard,medium,hard,hard", seed=9)
    try:
        files_a = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
        assert files_a == files_b
        skip_names = {"run_eval.sh", "latent_spec.json", "generation_manifest.json"}
        for rel in files_a:
            if rel.name in skip_names:
                continue
            left = (first / rel).read_bytes()
            right = (second / rel).read_bytes()
            if rel.suffix in {".py", ".md", ".sh", ".yaml", ".yml"}:
                assert left == right, rel
    finally:
        shutil.rmtree(first, ignore_errors=True)
        shutil.rmtree(second, ignore_errors=True)


# ---------------------------------------------------------------------------
# Generator semantics
# ---------------------------------------------------------------------------

def test_generated_instances_are_semantically_valid_and_deterministic() -> None:
    levels_grid = list(itertools.product(*_all_axis_levels()))
    assert len(levels_grid) == 3 * 3 * 3 * 2
    for levels in levels_grid:
        first = _instance_from_levels(list(levels), seed=3)
        second = _instance_from_levels(list(levels), seed=3)
        assert first == second
        assert NET.is_semantically_valid(first)
        assert NET.pairwise_nonempty(first)


def test_recursive_depth_changes_constraint_structure() -> None:
    shallow = NET.generate_instance(
        depth=1, domain_size=3, regime=NET.TREE, label_mode=NET.TRANSPARENT, seed=0
    )
    deep = NET.generate_instance(
        depth=3, domain_size=3, regime=NET.TREE, label_mode=NET.TRANSPARENT, seed=0
    )
    assert NET.region_count(shallow) == 3
    assert NET.region_count(deep) == 15
    assert NET.max_name_depth(shallow) == 1
    assert NET.max_name_depth(deep) == 3
    assert NET.overlap_count(deep) > NET.overlap_count(shallow)
    assert not NET.has_undirected_cycle(shallow)
    assert not NET.has_undirected_cycle(deep)
    assert not NET.has_skip_level_overlap(shallow)
    cyclic_deep = NET.generate_instance(
        depth=3, domain_size=3, regime=NET.CYCLIC_SAT, label_mode=NET.TRANSPARENT, seed=0
    )
    assert NET.has_skip_level_overlap(cyclic_deep)
    assert NET.has_undirected_cycle(cyclic_deep)


def test_state_space_axis_changes_domain_size() -> None:
    small = NET.generate_instance(
        depth=1, domain_size=3, regime=NET.TREE, label_mode=NET.TRANSPARENT, seed=1
    )
    large = NET.generate_instance(
        depth=1, domain_size=7, regime=NET.TREE, label_mode=NET.TRANSPARENT, seed=1
    )
    small_sizes = {len(spec["domain"]) for spec in small["regions"].values()}
    large_sizes = {len(spec["domain"]) for spec in large["regions"].values()}
    assert 3 in small_sizes
    assert 7 in large_sizes
    assert max(large_sizes) > max(small_sizes)


def test_gluing_regime_changes_satisfiability_without_empty_local_data() -> None:
    tree = NET.generate_instance(
        depth=2, domain_size=5, regime=NET.TREE, label_mode=NET.TRANSPARENT, seed=2
    )
    sat_cycle = NET.generate_instance(
        depth=2, domain_size=5, regime=NET.CYCLIC_SAT, label_mode=NET.TRANSPARENT, seed=2
    )
    unsat_cycle = NET.generate_instance(
        depth=2, domain_size=5, regime=NET.CYCLIC_UNSAT, label_mode=NET.TRANSPARENT, seed=2
    )
    assert NET.oracle_satisfiable(tree) is True
    assert NET.oracle_satisfiable(sat_cycle) is True
    assert NET.oracle_satisfiable(unsat_cycle) is False
    assert NET.pairwise_nonempty(unsat_cycle)
    assert NET.has_undirected_cycle(sat_cycle)
    assert NET.has_undirected_cycle(unsat_cycle)
    assert not NET.has_undirected_cycle(tree)
    naive = NET.naive_independent_assignment(unsat_cycle)
    ok, _ = NET.validate_assignment(unsat_cycle, naive)
    assert ok is False
    forest = NET.naive_spanning_forest_assignment(unsat_cycle)
    ok, _ = NET.validate_assignment(unsat_cycle, forest)
    assert ok is False


def test_label_opacity_preserves_answer_and_changes_presentation() -> None:
    shared = dict(depth=2, domain_size=5, regime=NET.CYCLIC_SAT, seed=8)
    clear = NET.generate_instance(label_mode=NET.TRANSPARENT, **shared)
    opaque = NET.generate_instance(label_mode=NET.OPAQUE, **shared)
    assert NET.oracle_satisfiable(clear) is True
    assert NET.oracle_satisfiable(opaque) is True
    clear_labels = {lab for spec in clear["regions"].values() for lab in spec["domain"]}
    opaque_labels = {lab for spec in opaque["regions"].values() for lab in spec["domain"]}
    assert any(lab.startswith("v") and lab[1:].isdigit() for lab in clear_labels)
    assert not any(lab.startswith("v") and lab[1:].isdigit() for lab in opaque_labels)
    relabeled = NET.relabel_instance(clear, seed=99)
    assert NET.oracle_satisfiable(relabeled) is True
    assert relabeled["regions"].keys() == clear["regions"].keys()
    assert relabeled != clear


def test_known_solvable_and_unsatisfiable_examples() -> None:
    solvable = NET.example_solvable_cycle()
    obstructed = NET.example_obstructed_cycle()
    assert NET.oracle_satisfiable(solvable) is True
    assignment = NET.oracle_solution(solvable)
    assert assignment is not None
    ok, _ = NET.validate_assignment(solvable, assignment)
    assert ok
    assert NET.oracle_satisfiable(obstructed) is False
    assert NET.pairwise_nonempty(obstructed)
    for asg in (
        NET.naive_independent_assignment(obstructed),
        NET.naive_spanning_forest_assignment(obstructed),
    ):
        ok, _ = NET.validate_assignment(obstructed, asg)
        assert ok is False
    copied = NET.naive_copy_shared_label(obstructed)
    assert copied is not None
    ok, _ = NET.validate_assignment(obstructed, copied)
    assert ok is False


def test_relabelling_invariance_on_obstruction() -> None:
    obstructed = NET.example_obstructed_cycle()
    relabeled = NET.relabel_instance(obstructed, seed=5)
    assert NET.oracle_satisfiable(relabeled) is False
    assert NET.pairwise_nonempty(relabeled)
    sat = NET.example_solvable_cycle()
    sat_relabeled = NET.relabel_instance(sat, seed=5)
    assert NET.oracle_satisfiable(sat_relabeled) is True


def test_held_out_size_is_beyond_naive_cartesian_and_oracle_is_fast() -> None:
    large = NET.generate_instance(
        depth=3, domain_size=7, regime=NET.CYCLIC_UNSAT, label_mode=NET.OPAQUE, seed=0
    )
    assert NET.cartesian_size(large) > 1_000_000
    assert NET.oracle_satisfiable(large) is False


def test_oracle_is_independent_of_the_candidate_solver() -> None:
    source = inspect.getsource(NET)
    assert "solver.py" not in source
    assert "RegionNetworkSolver" not in source
    assert "%%MODEL_CLASS%%" not in source
    solvable = NET.example_solvable_cycle()

    def always_unsat(_instance):
        return {"status": "unsat"}

    assert NET.oracle_satisfiable(solvable) is True
    assert NET.evaluate_solve_fn(always_unsat, solvable) is False


def test_malformed_and_semantically_invalid_outputs_are_rejected() -> None:
    inst = NET.example_local_path_sat()
    assert NET.parse_solve_output(inst, "nope")[0] is None
    assert NET.parse_solve_output(inst, {"status": "maybe"})[0] is None
    assert NET.parse_solve_output(inst, {"status": "sat"})[0] is None
    assert NET.parse_solve_output(
        inst, {"status": "sat", "assignment": {"cell_a": "p"}}
    )[0] is None
    assert NET.parse_solve_output(
        inst, {"status": "sat", "assignment": {"cell_a": "q", "cell_b": "s"}}
    )[0] is None
    good = {"status": "sat", "assignment": {"cell_a": "p", "cell_b": "r"}}
    parsed, err = NET.parse_solve_output(inst, good)
    assert parsed is not None and not err

    def boom(_instance):
        raise RuntimeError("candidate crashed")

    assert NET.evaluate_solve_fn(boom, inst) is False


def test_baseline_fails_hidden_properties_and_reference_passes() -> None:
    checks_ref = NET.grade_solver(
        NET.reference_solve,
        depth=2,
        domain_size=5,
        regime=NET.CYCLIC_UNSAT,
        label_mode=NET.OPAQUE,
        seed=6,
    )
    assert all(checks_ref.values()), checks_ref
    assert set(checks_ref) == set(NET.CHECK_NAMES)

    checks_base = NET.grade_solver(
        _baseline_solve,
        depth=2,
        domain_size=5,
        regime=NET.CYCLIC_UNSAT,
        label_mode=NET.OPAQUE,
        seed=6,
    )
    assert checks_base["local_path_sat"] is True
    assert checks_base["obstructed_cycle"] is False
    assert checks_base["nested_recursive"] is False
    assert checks_base["cyclic_unsat_generated"] is False
    assert sum(checks_base.values()) < sum(checks_ref.values())
    accuracy_base = sum(checks_base.values()) / len(checks_base)
    accuracy_ref = sum(checks_ref.values()) / len(checks_ref)
    assert accuracy_ref == 1.0
    assert accuracy_base < 0.6


def test_visible_tests_pass_on_the_unmodified_baseline() -> None:
    generated = _generate_env("test_rg_visible", "easy,easy,easy,easy", seed=1)
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


def test_scoring_partial_versus_total_success() -> None:
    ref = NET.grade_solver(
        NET.reference_solve,
        depth=1,
        domain_size=3,
        regime=NET.TREE,
        label_mode=NET.TRANSPARENT,
        seed=0,
    )
    base = NET.grade_solver(
        _baseline_solve,
        depth=1,
        domain_size=3,
        regime=NET.TREE,
        label_mode=NET.TRANSPARENT,
        seed=0,
    )

    def mix(instance):
        # Correct on the tiny visible-like path, wrong elsewhere.
        if set(instance["regions"]) == {"cell_a", "cell_b"}:
            return NET.reference_solve(instance)
        return _baseline_solve(instance)

    mixed = NET.grade_solver(
        mix,
        depth=1,
        domain_size=3,
        regime=NET.TREE,
        label_mode=NET.TRANSPARENT,
        seed=0,
    )
    assert sum(ref.values()) == len(NET.CHECK_NAMES)
    assert 0 < sum(mixed.values()) < len(NET.CHECK_NAMES)
    assert sum(base.values()) <= sum(mixed.values())


def test_timeout_is_not_treated_as_unsat() -> None:
    source = (FILES / "judge.py").read_text(encoding="utf-8") + NET_PATH.read_text(
        encoding="utf-8"
    )
    assert "OracleBudgetExceeded" in source
    assert "RUNTIME_ERROR" in (FILES / "judge.py").read_text(encoding="utf-8")
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.oracle_solution(NET.example_solvable_cycle(), max_nodes=1)


def test_naive_copying_fails_on_nested_transparent_instances() -> None:
    inst = NET.generate_instance(
        depth=2, domain_size=5, regime=NET.TREE, label_mode=NET.TRANSPARENT, seed=4
    )
    copied = NET.naive_copy_shared_label(inst)
    if copied is not None:
        ok, _ = NET.validate_assignment(inst, copied)
        assert ok is False
    independent = NET.naive_independent_assignment(inst)
    ok, _ = NET.validate_assignment(inst, independent)
    assert ok is False
    assert NET.oracle_satisfiable(inst) is True


def test_generated_workspace_solver_is_the_buggy_baseline() -> None:
    generated = _generate_env("test_rg_baseline", "medium,medium,medium,hard", seed=2)
    try:
        solver_path = generated / "agent" / "workspace" / "solver.py"
        spec = importlib.util.spec_from_file_location("generated_solver", solver_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        inst = NET.generate_instance(
            depth=2, domain_size=5, regime=NET.CYCLIC_SAT, label_mode=NET.OPAQUE, seed=2
        )
        assert NET.oracle_satisfiable(inst) is True
        assert NET.evaluate_solve_fn(module.RegionNetworkSolver().solve, inst) is False
    finally:
        shutil.rmtree(generated, ignore_errors=True)
