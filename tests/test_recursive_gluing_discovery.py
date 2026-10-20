"""Tests for recursive_gluing_discovery: compact grammar sibling of v0.

v0 (`recursive_gluing`) remains the fully expanded CSP control. These tests
check that the agent-facing instance is a recursive grammar, that the compact
certificate matches an independent interface-summary oracle, that a shallow
expanded CSP agrees, and that each axis changes the intended property.
"""
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FILES = ROOT / "envs" / "cat_theo" / "recursive_gluing_discovery" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_gluing_discovery" / "config.yaml"
NET_PATH = FILES / "network.py"
V0_FILES = ROOT / "envs" / "cat_theo" / "recursive_gluing" / "files"


def _load_network():
    spec = importlib.util.spec_from_file_location("rgd_network", NET_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NET = _load_network()


def _load_baseline():
    text = (FILES / "solver.py").read_text(encoding="utf-8")
    text = text.replace("%%MODEL_CLASS%%", "GrammarInterfaceSolver")
    namespace: dict = {}
    exec(compile(text, "solver.py", "exec"), namespace)
    return namespace["GrammarInterfaceSolver"]()


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
        "label_opacity",
        "structural_ambiguity",
    ]
    assert config["axes"][0]["class"] == "task"
    assert config["axes"][1]["class"] == "task"
    assert config["axes"][2]["class"] == "task"
    assert config["axes"][3]["class"] == "presentation"
    assert config["axes"][4]["class"] == "task"
    assert config["layout"]["judge/network.py"] == "network.py"
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert "recursive_gluing" in registry["environments"]
    assert registry["environments"]["recursive_gluing_discovery"].endswith(
        "recursive_gluing_discovery/config.yaml"
    )
    prompt = (FILES / "prompt.md").read_text(encoding="utf-8").lower()
    for banned in (
        "sheaf",
        "holonomy",
        "affine",
        "group action",
        "logarithm",
        "z/n",
        "dynamic programming",
        "canonical",
        "transducer",
    ):
        assert banned not in prompt
    source = NET_PATH.read_text(encoding="utf-8")
    assert "%%" not in source
    assert "experiment_arms" not in source
    assert "experiment_arms" not in (FILES / "judge.py").read_text(encoding="utf-8")


def test_v0_control_is_still_an_expanded_csp() -> None:
    v0 = (V0_FILES / "network.py").read_text(encoding="utf-8")
    assert "generate_instance" in v0
    assert "regions" in v0
    disc = (FILES / "prompt.md").read_text(encoding="utf-8")
    assert "productions" in disc
    assert "realizable" in disc


def test_input_is_compact_grammar_not_expanded_csp() -> None:
    grammar = NET.generate_grammar(
        depth=6,
        interface_size=5,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.OPAQUE,
        ambiguity=NET.CLEAN,
        seed=3,
    )
    public = NET.public_grammar(grammar)
    assert set(public) == {"root", "depth", "modules", "productions", "closing"}
    assert "regions" not in public
    assert "overlaps" not in public
    assert public["depth"] == 6
    assert "stem" in public["modules"]
    assert "tip" in public["modules"]
    assert public["modules"]["tip"]["kind"] == "leaf"
    assert public["modules"]["stem"]["kind"] == "branch"
    assert "deeper" in public["productions"]["stem"]
    assert "depth_1" in public["productions"]["stem"]
    assert NET.unfolded_occurrences(6) == 127
    assert NET.compact_input_bytes(grammar) < 20_000
    assert NET.unfolded_occurrences(12) == 8191


def test_axes_move_the_task() -> None:
    shallow = NET.generate_grammar(
        depth=3, interface_size=5, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=0
    )
    deep = NET.generate_grammar(
        depth=12, interface_size=5, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=0
    )
    assert NET.unfolded_occurrences(3) == 15
    assert NET.unfolded_occurrences(12) == 8191
    assert NET.compact_input_bytes(deep) < 4 * NET.compact_input_bytes(shallow) + 200
    small = NET.generate_grammar(
        depth=3, interface_size=3, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=1
    )
    large = NET.generate_grammar(
        depth=3, interface_size=7, regime=NET.TREE, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=1
    )
    assert len(small["modules"]["tip"]["pairs"]) == 3
    assert len(large["modules"]["tip"]["pairs"]) == 7
    sat = NET.generate_grammar(
        depth=3, interface_size=5, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=2
    )
    unsat = NET.generate_grammar(
        depth=3, interface_size=5, regime=NET.CYCLIC_UNSAT, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=2
    )
    assert NET.grammar_satisfiable(sat) is True
    assert NET.grammar_satisfiable(unsat) is False
    assert NET.local_tables_nonempty(unsat)
    opaque = NET.generate_grammar(
        depth=3, interface_size=5, regime=NET.CYCLIC_SAT, opacity=NET.OPAQUE, ambiguity=NET.CLEAN, seed=4
    )
    assert set(opaque["modules"]["stem"]["ports_domain"]) != set(
        opaque["modules"]["tip"]["ports_domain"]
    )
    assert NET.grammar_satisfiable(opaque) is True
    clean = NET.generate_grammar(
        depth=3, interface_size=5, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, ambiguity=NET.CLEAN, seed=5
    )
    decoy = NET.generate_grammar(
        depth=3, interface_size=5, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, ambiguity=NET.DECOY, seed=5
    )
    assert "weed" not in clean["modules"]
    assert "weed" in decoy["modules"]
    assert decoy["productions"]["stem"]["depth_1"]["right"] == "weed"
    assert NET.compact_summaries(clean) != NET.compact_summaries(decoy)


def test_compact_oracle_agrees_with_shallow_expansion() -> None:
    for depth in (1, 2, 3):
        for regime in (NET.TREE, NET.CYCLIC_SAT, NET.CYCLIC_UNSAT):
            for opacity in (NET.TRANSPARENT, NET.OPAQUE):
                for ambiguity in (NET.CLEAN, NET.DECOY):
                    grammar = NET.generate_grammar(
                        depth=depth,
                        interface_size=5,
                        regime=regime,
                        opacity=opacity,
                        ambiguity=ambiguity,
                        seed=10 + depth,
                    )
                    compact_sat = NET.grammar_satisfiable(grammar)
                    expanded_sat = NET.expanded_satisfiable(grammar)
                    assert compact_sat is expanded_sat, (depth, regime, opacity, ambiguity)
                    compact_root = NET.root_accepted_pairs(grammar, NET.compact_summaries(grammar))
                    expanded_root = NET.expanded_root_pairs(grammar)
                    assert compact_root == expanded_root, (depth, regime, opacity, ambiguity)


def test_hard_depth_is_not_expanded() -> None:
    grammar = NET.generate_grammar(
        depth=12,
        interface_size=5,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.OPAQUE,
        ambiguity=NET.CLEAN,
        seed=0,
    )
    cert = NET.reference_certificate(grammar)
    assert cert["status"] == "unsat"
    assert NET.summary_cells(cert["realizable"]) < 200
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.expand_grammar(grammar)


def test_timeout_is_not_unsat() -> None:
    grammar = NET.example_visible_grammar()
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.compact_summaries(grammar, max_nodes=1)
    assert NET.grammar_satisfiable(grammar) is True


def test_baselines_separate_copy_from_compact() -> None:
    visible = NET.example_visible_grammar()
    assert NET.evaluate_solver(NET.arm_copy_leaf_upward, visible) is True
    assert NET.evaluate_solver(NET.arm_compact, visible) is True
    unsat = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.CLEAN,
        seed=8,
    )
    assert NET.evaluate_solver(NET.arm_compact, unsat) is True
    assert NET.evaluate_solver(NET.arm_copy_leaf_upward, unsat) is False
    assert NET.evaluate_solver(NET.arm_given_canonical, unsat) is True
    opaque = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.TREE,
        opacity=NET.OPAQUE,
        ambiguity=NET.CLEAN,
        seed=8,
    )
    assert NET.evaluate_solver(NET.arm_compact, opaque) is True
    assert NET.evaluate_solver(NET.arm_copy_leaf_upward, opaque) is False
    decoy = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_SAT,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.DECOY,
        seed=8,
    )
    assert NET.evaluate_solver(NET.arm_compact, decoy) is True
    assert NET.evaluate_solver(NET.arm_copy_leaf_upward, decoy) is False
    twist = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_SAT,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.CLEAN,
        seed=8,
        mid_delta=1,
    )
    assert NET.evaluate_solver(NET.arm_compact, twist) is True
    assert NET.evaluate_solver(NET.arm_copy_leaf_upward, twist) is False
    shallow = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.OPAQUE,
        ambiguity=NET.CLEAN,
        seed=1,
    )
    assert NET.evaluate_solver(NET.arm_expanded, shallow) is True


def test_relabel_preserves_sat_and_changes_labels() -> None:
    grammar = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_SAT,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.CLEAN,
        seed=9,
    )
    twin = NET.relabel_grammar(grammar, seed=21)
    assert NET.grammar_satisfiable(grammar) is True
    assert NET.grammar_satisfiable(twin) is True
    assert grammar["modules"]["stem"]["ports_domain"] != twin["modules"]["stem"]["ports_domain"]
    assert NET.evaluate_solver(NET.arm_compact, twin) is True
    assert NET.evaluate_solver(NET.arm_copy_leaf_upward, twin) is False


def test_grade_reference_vs_baseline() -> None:
    kwargs = dict(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.OPAQUE,
        ambiguity=NET.DECOY,
        seed=6,
    )
    ref = NET.grade_solver(NET.arm_compact, **kwargs)
    assert all(ref.values()), ref
    copy = NET.grade_solver(NET.arm_copy_leaf_upward, **kwargs)
    base = NET.grade_solver(_load_baseline().solve, **kwargs)
    assert copy["local_visible"] is True
    assert base["local_visible"] is True
    assert copy["assembled_unsat"] is False
    assert copy["decoy_heldout"] is False
    assert copy["heldout_twist"] is False
    assert sum(copy.values()) < sum(ref.values())
    assert sum(base.values()) < sum(ref.values())


def test_oracle_independent_of_candidate() -> None:
    source = inspect.getsource(NET)
    assert "solver.py" not in source
    assert "GrammarInterfaceSolver" not in source
    grammar = NET.example_visible_grammar()
    assert NET.grammar_satisfiable(grammar) is True

    def always_unsat(_grammar):
        return {"status": "unsat", "realizable": {}}

    assert NET.evaluate_solver(always_unsat, grammar) is False


def test_scaling_reports_exponential_unfolding() -> None:
    rows = NET.measure_scaling(interface_size=5, regime=NET.CYCLIC_UNSAT, seed=0)
    by_depth = {row["depth"]: row for row in rows}
    assert by_depth[1]["occurrences"] == 3
    assert by_depth[12]["occurrences"] == 8191
    assert by_depth[12]["compact_bytes"] < 50_000
    assert by_depth[12]["summary_cells"] < 200
    assert by_depth[12]["expanded_ms"] is None
    assert by_depth[3]["expanded_ms"] is not None
    assert by_depth[12]["status"] == "unsat"
    assert by_depth[1]["compact_ms"] < 1_000
    assert by_depth[12]["compact_ms"] < 1_000


def test_generation_cli() -> None:
    covering = [
        "easy,easy,easy,easy,easy",
        "hard,easy,easy,easy,easy",
        "easy,hard,easy,easy,easy",
        "easy,easy,hard,easy,easy",
        "easy,easy,easy,hard,easy",
        "easy,easy,easy,easy,hard",
        "hard,hard,hard,hard,hard",
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
            judge = (generated / "judge" / "judge.py").read_text(encoding="utf-8")
            assert "GrammarInterfaceSolver" in judge
            prompt = (generated / "agent" / "workspace" / "prompt.md").read_text(encoding="utf-8")
            assert "productions" in prompt
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)


def test_occurrence_formula_matches_shallow_unfoldings() -> None:
    for depth in (1, 2, 3, 4):
        grammar = NET.generate_grammar(
            depth=depth,
            interface_size=5,
            regime=NET.CYCLIC_UNSAT,
            opacity=NET.OPAQUE,
            ambiguity=NET.CLEAN,
            seed=0,
        )
        instance = NET.expand_grammar(grammar)
        assert NET.expanded_occurrence_count(instance) == NET.unfolded_occurrences(depth)
        assert NET.unfolded_occurrences(depth) == (1 << (depth + 1)) - 1
        assert len(instance["regions"]) == NET.expanded_port_variables(depth)
        assert len(instance["overlaps"]) == NET.expanded_overlap_count(depth, closing=True)


def test_expanded_counts_match_formulas_including_tree() -> None:
    tree = NET.generate_grammar(
        depth=3,
        interface_size=3,
        regime=NET.TREE,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.CLEAN,
        seed=1,
    )
    inst = NET.expand_grammar(tree)
    assert NET.expanded_occurrence_count(inst) == 15
    assert len(inst["regions"]) == 30
    assert len(inst["overlaps"]) == NET.expanded_overlap_count(3, closing=False)
    unsat = NET.generate_grammar(
        depth=3,
        interface_size=3,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.CLEAN,
        seed=1,
    )
    inst_u = NET.expand_grammar(unsat)
    assert len(inst_u["overlaps"]) == NET.expanded_overlap_count(3, closing=True)
    assert len(inst_u["overlaps"]) == len(inst["overlaps"]) + 1


def test_compact_input_smaller_than_measured_expansion() -> None:
    for depth in (3, 6):
        grammar = NET.generate_grammar(
            depth=depth,
            interface_size=5,
            regime=NET.CYCLIC_UNSAT,
            opacity=NET.OPAQUE,
            ambiguity=NET.CLEAN,
            seed=0,
        )
        compact = NET.compact_input_bytes(grammar)
        expanded = NET.expand_grammar(grammar, max_depth=depth)
        expanded_bytes = len(json.dumps(expanded, separators=(",", ":")))
        assert compact < expanded_bytes
        assert expanded_bytes / compact > 5
        assert NET.expanded_occurrence_count(expanded) == NET.unfolded_occurrences(depth)


def test_certificate_grows_with_depth_not_occurrences() -> None:
    cells = []
    keys = []
    occ = []
    for depth in (3, 6, 12, 24):
        grammar = NET.generate_grammar(
            depth=depth,
            interface_size=5,
            regime=NET.CYCLIC_UNSAT,
            opacity=NET.OPAQUE,
            ambiguity=NET.CLEAN,
            seed=0,
        )
        cert = NET.reference_certificate(grammar)
        cells.append(NET.summary_cells(cert["realizable"]))
        keys.append(NET.summary_depth_keys(cert["realizable"]))
        occ.append(NET.unfolded_occurrences(depth))
        blob = json.dumps(cert)
        assert "root/L" not in blob
        assert cert["realizable"]["stem"].keys() == {str(k) for k in range(1, depth + 1)}
    assert keys == [4, 7, 13, 25]  # tip@0 + stem@1..d
    assert cells[0] < cells[-1] < 200
    assert occ[-1] / occ[0] > 1000
    assert cells[-1] / cells[0] < 10


def test_deep_compact_oracle_does_not_materialize() -> None:
    grammar = NET.generate_grammar(
        depth=48,
        interface_size=5,
        regime=NET.CYCLIC_UNSAT,
        opacity=NET.OPAQUE,
        ambiguity=NET.CLEAN,
        seed=0,
    )
    cert = NET.reference_certificate(grammar)
    ok, reason = NET.verify_certificate(grammar, cert)
    assert ok, reason
    assert cert["status"] == "unsat"
    assert NET.summary_cells(cert["realizable"]) == 5 * (48 + 1)
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.expand_grammar(grammar)
    assert "regions" not in NET.public_grammar(grammar)


def test_label_opacity_is_per_type_not_per_occurrence() -> None:
    grammar = NET.generate_grammar(
        depth=3,
        interface_size=5,
        regime=NET.CYCLIC_SAT,
        opacity=NET.OPAQUE,
        ambiguity=NET.DECOY,
        seed=4,
    )
    instance = NET.expand_grammar(grammar)
    domains = {tuple(spec["domain"]) for spec in instance["regions"].values()}
    assert len(instance["regions"]) == NET.expanded_port_variables(3)
    assert len(domains) == 3  # stem, tip, weed — shared across occurrences
    assert len(domains) < NET.unfolded_occurrences(3)
    twin = NET.relabel_grammar(grammar, seed=21)
    assert NET.grammar_satisfiable(twin) is NET.grammar_satisfiable(grammar)
    assert twin["modules"]["stem"]["ports_domain"] != grammar["modules"]["stem"]["ports_domain"]


def test_resource_exhaustion_is_not_recorded_as_unsat() -> None:
    grammar = NET.generate_grammar(
        depth=6,
        interface_size=5,
        regime=NET.TREE,
        opacity=NET.TRANSPARENT,
        ambiguity=NET.CLEAN,
        seed=0,
    )
    assert NET.grammar_satisfiable(grammar) is True
    with pytest.raises(NET.OracleBudgetExceeded, match="not evidence of unsat"):
        NET.expand_grammar(grammar, max_depth=4)
    with pytest.raises(NET.OracleBudgetExceeded, match="refusing to call this unsat"):
        NET.compact_summaries(grammar, max_nodes=1)


def test_scaling_script_is_deterministic_and_does_not_touch_campaigns(
    tmp_path: Path,
) -> None:
    script = ROOT / "tools" / "recursive_gluing_scaling.py"
    source = script.read_text(encoding="utf-8")
    assert "experiment_arms" not in source
    assert "campaigns" not in source
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    cmd = [
        sys.executable,
        str(script),
        "--compact-depths",
        "3",
        "--expand-depths",
        "3",
        "--attempt-expand",
        "none",
        "--repeats",
        "1",
        "--seed",
        "0",
        "--interface-size",
        "5",
        "--regime",
        "cyclic_unsat",
    ]
    for dest in (out_a, out_b):
        proc = subprocess.run(
            [*cmd, "--json", str(dest)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
    a = json.loads(out_a.read_text(encoding="utf-8"))
    b = json.loads(out_b.read_text(encoding="utf-8"))
    assert a["config"]["seed"] == b["config"]["seed"] == 0
    assert a["config"]["campaign_state"] == "untouched"
    assert a["compact"][0]["grammar_bytes"] == b["compact"][0]["grammar_bytes"]
    assert a["compact"][0]["occurrences"] == 15
    assert a["expanded"][0]["occurrences"] == 15
    assert a["expanded"][0]["variables"] == 30
    assert a["expanded"][0]["used_compact_oracle"] is False
    assert a["expanded"][0]["kind"] == "measured"
    assert a["compact"][0]["status"] == "unsat"
    assert a["expanded"][0]["sat"] is False


def test_visible_tests_pass_on_baseline() -> None:
    generated = _generate_env("test_rgd_visible", "easy,easy,easy,easy,easy", seed=1)
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
