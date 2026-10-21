"""Tests for recursive_epistemic_gluing."""
from __future__ import annotations

import ast
import inspect
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "envs" / "cat_theo" / "recursive_epistemic_gluing" / "files"
CONFIG = ROOT / "envs" / "cat_theo" / "recursive_epistemic_gluing" / "config.yaml"
NET_PATH = FILES / "network.py"

BANNED_WORD = re.compile(
    r"\b(sheaf|presheaf|section|gluing|glue|holonomy|monodromy|"
    r"cohomology|čech|cech|local[ -]system|fixed[ -]point)\b",
    re.IGNORECASE,
)


def _load_network():
    spec = __import__("importlib.util", fromlist=["spec_from_file_location"]).spec_from_file_location(
        "epi_net", NET_PATH
    )
    module = __import__("importlib.util", fromlist=["module_from_spec"]).module_from_spec(spec)
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
    assert BANNED_WORD.search(prompt) is None, BANNED_WORD.search(prompt)
    assert "experiment_arms" not in NET_PATH.read_text(encoding="utf-8")
    assert "transfer summar" not in prompt


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


# ---------------------------------------------------------------------------
# Phase 6: thirteen categories (existing tests above stay intact)
# ---------------------------------------------------------------------------

def _pub_dump(model: dict) -> str:
    return json.dumps(NET.public_model(model), sort_keys=True, separators=(",", ":"))


def test_1_deterministic_generation() -> None:
    for cls in NET.INSTANCE_CLASSES:
        a = NET.generate_class(cls, 7, NET.TRANSPARENT)
        b = NET.generate_class(cls, 7, NET.TRANSPARENT)
        assert _pub_dump(a) == _pub_dump(b)


def test_2_independent_verification_of_reference_witnesses() -> None:
    for cls in NET.INSTANCE_CLASSES:
        model = NET.generate_class(cls, 3)
        cert = NET.reference_certificate(model)
        ok, reason = NET.verify_certificate(model, cert)
        assert ok, (cls, reason, cert)


def test_3_bounded_exact_judge_on_small_cases() -> None:
    for seed in range(8):
        model = NET.generate_model(
            depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, order=seed % 2, seed=seed
        )
        assert NET.cross_check_flat(model)
        cert = NET.reference_certificate(model)
        ok, reason = NET.verify_certificate(model, cert)
        assert ok, reason


def test_4_instance_class_properties_dev_and_heldout() -> None:
    for cls in NET.INSTANCE_CLASSES:
        for seed in list(NET.DEV_SEEDS) + list(NET.HELD_OUT_SEEDS):
            model = NET.generate_class(cls, seed, NET.TRANSPARENT)
            got = NET.classify(model)
            assert got == cls, (cls, seed, got, NET.task_sat(model), NET.bundle_possible(model))
            # membership must ignore meta
            model["meta"] = {"class": "nope"}
            assert NET.classify(model) == cls


def test_5_handwritten_neg_deep_and_neg_recursive() -> None:
    deep = NET.handwritten_neg_deep()
    rec = NET.handwritten_neg_recursive()
    assert NET.classify(deep) == NET.NEG_DEEP
    assert NET.classify(rec) == NET.NEG_RECURSIVE
    assert NET.local_ok(deep) and NET.pairwise_ok(deep) and NET.triple_ok(deep)
    assert NET.bundle_possible(deep) is False
    assert NET.task_sat(deep) is False
    assert NET.local_ok(rec) and NET.pairwise_ok(rec)
    assert NET.task_sat(rec) is False
    assert NET.task_sat(NET.flatten_task_model(rec)) is True
    for model in (deep, rec):
        cert = NET.reference_certificate(model)
        ok, reason = NET.verify_certificate(model, cert)
        assert ok, reason
        # solver and judge agree
        assert NET.evaluate_solver(NET.arm_reference, model) is True


def test_6_flip_pair_and_presentation_twin() -> None:
    rec = NET.handwritten_neg_recursive()
    flipped = NET.flip_neg_recursive(rec)
    assert NET.task_sat(rec) is False
    assert NET.task_sat(flipped) is True
    ok, reason = NET.verify_certificate(flipped, NET.reference_certificate(flipped))
    assert ok, reason
    twin = NET.presentation_twin(rec, 21)
    assert NET.task_sat(twin) is False
    assert NET.classify(twin) == NET.NEG_RECURSIVE
    assert twin["frames"][twin["levels"][0]]["worlds"] != rec["frames"]["outer"]["worlds"]
    ok, reason = NET.verify_certificate(twin, NET.reference_certificate(twin))
    assert ok, reason


def test_7_recursion_necessity_bflat_bk() -> None:
    rec = NET.handwritten_neg_recursive()
    pos = NET.handwritten_pos_recursive()
    assert NET.task_sat(rec) is False
    assert NET.task_sat(NET.flatten_task_model(rec)) is True
    assert NET.task_sat(NET.bounded_task_model(rec, 0)) is True
    assert NET.task_sat(NET.bounded_task_model(rec, 1)) is True
    assert NET.task_sat(NET.bounded_task_model(rec, 2)) is False
    assert NET.task_sat(pos) is True
    assert NET.task_sat(NET.flatten_task_model(pos)) is False
    assert NET.classify(pos) == NET.POS_RECURSIVE


def test_8_local_and_pairwise_of_nontrivial_obstructions() -> None:
    deep = NET.handwritten_neg_deep()
    rec = NET.handwritten_neg_recursive()
    for model in (deep, rec):
        assert NET.local_ok(model)
        assert NET.pairwise_ok(model)
    cells = NET.cells_for_reports(deep["frames"]["outer"], deep["bundle"])
    assert NET.kwise_nonempty(cells, 2)
    assert NET.kwise_nonempty(cells, 3)
    assert not NET.kwise_nonempty(cells, 4)


def test_9_correctness_after_renaming_or_reordering() -> None:
    for cls in NET.INSTANCE_CLASSES:
        model = NET.generate_class(cls, 5, NET.TRANSPARENT)
        twin = NET.presentation_twin(model, 99)
        assert NET.task_sat(model) == NET.task_sat(twin)
        assert NET.query_value(model) == NET.query_value(twin)
        assert NET.bundle_possible(model) == NET.bundle_possible(twin)
        ok, reason = NET.verify_certificate(twin, NET.reference_certificate(twin))
        assert ok, (cls, reason)


def test_10_judge_independence_from_reference_and_metadata() -> None:
    source = inspect.getsource(NET.verify_certificate)
    assert "reference_certificate" not in source
    assert "arm_reference" not in source
    tree = ast.parse(NET_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "verify_certificate":
            body = ast.dump(node)
            assert "reference_certificate" not in body
            assert "arm_reference" not in body
    original_ref = NET.reference_certificate
    original_arm = NET.arm_reference

    def boom(*_a, **_k):
        raise AssertionError("reference solver must not be consulted by the judge")

    NET.reference_certificate = boom  # type: ignore[method-assign]
    NET.arm_reference = boom  # type: ignore[method-assign]
    try:
        for maker in (NET.handwritten_neg_deep, NET.handwritten_neg_recursive, NET.example_visible_model):
            model = maker()
            cert = original_ref(model)
            ok, reason = NET.verify_certificate(model, cert)
            assert ok, reason
            # hidden meta must not be required
            model = dict(model)
            model["meta"] = {"label": "sat"}
            ok, reason = NET.verify_certificate(model, cert)
            assert ok, reason
    finally:
        NET.reference_certificate = original_ref  # type: ignore[method-assign]
        NET.arm_reference = original_arm  # type: ignore[method-assign]


def test_certificate_rejects_truthy_non_booleans() -> None:
    """Regression: bool("false") is True; certificates must carry real bools."""
    true_model = NET.example_visible_model()
    assert NET.query_value(true_model) is True
    ok, reason = NET.verify_certificate(true_model, {"query_value": "false"})
    assert ok is False, reason
    assert "bool" in reason

    false_model = NET.generate_model(
        depth=1, regime=NET.TREE, opacity=NET.TRANSPARENT, order=1, seed=0
    )
    assert NET.query_value(false_model) is False
    assert NET.verify_certificate(false_model, {"query_value": False})[0] is True
    assert NET.verify_certificate(false_model, {"query_value": True})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": "true"})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": "false"})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": 0})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": 1})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": None})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": []})[0] is False
    assert NET.verify_certificate(false_model, {"query_value": {}})[0] is False

    assert NET.verify_certificate(true_model, {"query_value": True})[0] is True
    assert NET.verify_certificate(true_model, {"query_value": False})[0] is False
    assert NET.verify_certificate(true_model, {"query_value": "true"})[0] is False
    assert NET.verify_certificate(true_model, {"query_value": 1})[0] is False
    assert NET.verify_certificate(true_model, {"query_value": 0})[0] is False
    assert NET.verify_certificate(true_model, {"query_value": None})[0] is False
    assert NET.verify_certificate(true_model, {"query_value": ["query_value"]})[0] is False

    sat_bundle = NET.generate_model(
        depth=1, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, order=0, seed=1
    )
    unsat_bundle = NET.handwritten_neg_deep()
    assert NET.bundle_possible(sat_bundle) is True
    assert NET.bundle_possible(unsat_bundle) is False
    joint, _ = NET.joint_worlds(sat_bundle)
    good_sat = {"query_value": True, "bundle_possible": True, "joint_world": joint}
    assert NET.verify_certificate(sat_bundle, good_sat)[0] is True
    # Truthy non-bool must not pass even when it matches the correct answer.
    assert NET.verify_certificate(
        sat_bundle, {"query_value": True, "bundle_possible": "true", "joint_world": joint}
    )[0] is False
    assert NET.verify_certificate(
        sat_bundle, {"query_value": True, "bundle_possible": 1, "joint_world": joint}
    )[0] is False
    assert NET.verify_certificate(sat_bundle, {"query_value": True})[0] is False  # missing
    assert NET.verify_certificate(
        unsat_bundle, {"query_value": True, "bundle_possible": False}
    )[0] is True
    assert NET.verify_certificate(
        unsat_bundle, {"query_value": True, "bundle_possible": 0}
    )[0] is False
    assert NET.verify_certificate(
        unsat_bundle, {"query_value": True, "bundle_possible": "false"}
    )[0] is False
    assert NET.verify_certificate(
        unsat_bundle, {"query_value": True, "bundle_possible": None}
    )[0] is False
    assert NET.verify_certificate(
        unsat_bundle, {"query_value": True, "bundle_possible": []}
    )[0] is False
    rec = NET.handwritten_neg_recursive()
    assert NET.verify_certificate(rec, {"query_value": True, "bundle_possible": False})[0] is True
    assert NET.verify_certificate(rec, {"query_value": True, "bundle_possible": 0})[0] is False


def _imported_solver_modules(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    # Judge templates contain %%PLACEHOLDER%%; strip those so AST parse works.
    text = re.sub(r"%%[A-Z0-9_]+%%", "0", text)
    tree = ast.parse(text)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "solver" or alias.name.startswith("solver."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "solver" or mod.startswith("solver."):
                hits.append(mod)
            if any(alias.name == "solver" for alias in node.names):
                hits.append("from ... import solver")
    return hits


def test_checker_does_not_invoke_candidate_solver() -> None:
    """Trusted oracles may be shared; the evaluated candidate solver must not be."""
    import types

    assert _imported_solver_modules(NET_PATH) == []
    assert _imported_solver_modules(FILES / "judge.py") == []

    class BoomSolver(types.ModuleType):
        def __getattr__(self, name: str) -> None:
            raise AssertionError(f"candidate solver consulted for {name}")

        def solve(self, *_a, **_k):
            raise AssertionError("candidate solver.solve called")

    previous = sys.modules.get("solver")
    sys.modules["solver"] = BoomSolver("solver")
    try:
        true_model = NET.example_visible_model()
        ok, reason = NET.verify_certificate(true_model, {"query_value": True})
        assert ok, reason
        ok, reason = NET.verify_certificate(true_model, {"query_value": "false"})
        assert ok is False
        unsat = NET.handwritten_neg_deep()
        ok, reason = NET.verify_certificate(
            unsat, {"query_value": True, "bundle_possible": False}
        )
        assert ok, reason
    finally:
        if previous is None:
            sys.modules.pop("solver", None)
        else:
            sys.modules["solver"] = previous


def test_query_cross_checked_against_flattened_worlds() -> None:
    models = [
        NET.example_visible_model(),
        NET.handwritten_neg_deep(),
        NET.handwritten_neg_recursive(),
        NET.handwritten_pos_recursive(),
    ]
    for cls in NET.INSTANCE_CLASSES:
        for seed in range(6):
            models.append(NET.generate_class(cls, seed, NET.TRANSPARENT))
    for depth in (1, 2):
        for regime in (NET.TREE, NET.CYCLIC_SAT, NET.CYCLIC_UNSAT):
            for order in (0, 1, 2):
                models.append(
                    NET.generate_model(
                        depth=depth,
                        regime=regime,
                        opacity=NET.TRANSPARENT,
                        order=order,
                        seed=depth * 10 + order,
                    )
                )
    assert len(models) >= 40
    for model in models:
        nested = NET.query_value(model)
        flat = NET.query_value(NET.flatten_model(model))
        assert nested is flat
        assert NET.cross_check_flat(model) is True


def _independent_reports_possible(frame: dict, reports: dict | None) -> bool | None:
    if not reports:
        return None
    cells = []
    worlds = {str(w) for w in frame["worlds"]}
    for agent, world in reports.items():
        named = str(world)
        if named not in worlds:
            cells.append(set())
            continue
        cell = set()
        for block in frame["indist"][agent]:
            block_set = {str(x) for x in block}
            if named in block_set:
                cell = block_set
                break
        cells.append(cell)
    if any(len(c) == 0 for c in cells):
        return False
    inter = set(cells[0])
    for cell in cells[1:]:
        inter &= cell
    return bool(inter)


def test_bundle_verified_by_independent_cell_intersection() -> None:
    models = [
        NET.handwritten_neg_deep(),
        NET.handwritten_neg_recursive(),
        NET.generate_model(
            depth=1, regime=NET.CYCLIC_SAT, opacity=NET.TRANSPARENT, order=0, seed=1
        ),
        NET.generate_model(
            depth=1, regime=NET.CYCLIC_UNSAT, opacity=NET.TRANSPARENT, order=0, seed=1
        ),
        NET.generate_class(NET.POS_PLAIN, 1),
        NET.generate_class(NET.NEG_PAIRWISE, 2),
        NET.generate_class(NET.NEG_DEEP, 3),
        NET.generate_class(NET.NEG_RECURSIVE, 4),
        NET.generate_class(NET.NEG_LOCAL, 5),
    ]
    for model in models:
        outer = model["frames"][model["levels"][0]]
        outer_ok = _independent_reports_possible(outer, model.get("bundle"))
        inner_ok: bool | None = None
        if model.get("nested_bundle"):
            if len(model["levels"]) < 2:
                inner_ok = False
            else:
                inner = model["frames"][model["levels"][1]]
                inner_ok = _independent_reports_possible(inner, model["nested_bundle"])
        flags = [flag for flag in (outer_ok, inner_ok) if flag is not None]
        expected = None if not flags else all(flags)
        assert NET.bundle_possible(model) is expected
        if expected is None:
            continue
        cert: dict = {"query_value": bool(NET.query_value(model)), "bundle_possible": bool(expected)}
        if expected:
            joint, inner_j = NET.joint_worlds(model)
            if joint is not None:
                cert["joint_world"] = joint
            if inner_j is not None:
                cert["joint_inner"] = inner_j
        ok, reason = NET.verify_certificate(model, cert)
        assert ok, (reason, cert, expected)
        # Falsy/truthy coercions that match expected still fail.
        coerced = 1 if expected else 0
        bad = dict(cert)
        bad["bundle_possible"] = coerced
        assert NET.verify_certificate(model, bad)[0] is False


def test_11_budget_invalid_malformed_overlong() -> None:
    model = NET.example_visible_model()
    with pytest.raises(NET.OracleBudgetExceeded):
        NET.query_value(model, budget=0)
    assert NET.verify_certificate(model, None)[0] is False
    assert NET.verify_certificate(model, "unsat")[0] is False
    assert NET.verify_certificate(model, {})[0] is False
    assert NET.verify_certificate(model, {"query_value": False})[0] is False
    deep = NET.handwritten_neg_deep()
    # SAT claim without a joint world
    bad = {"query_value": True, "bundle_possible": True}
    assert NET.verify_certificate(deep, bad)[0] is False
    # SAT claim with a world not in every cell
    bad2 = {"query_value": True, "bundle_possible": True, "joint_world": "w0"}
    assert NET.verify_certificate(deep, bad2)[0] is False
    rec = NET.handwritten_neg_recursive()
    bad3 = {
        "query_value": True,
        "bundle_possible": True,
        "joint_world": "w1",
        "joint_inner": "u0",
    }
    assert NET.verify_certificate(rec, bad3)[0] is False
    # Correct UNSAT claims
    assert NET.verify_certificate(deep, {"query_value": True, "bundle_possible": False})[0] is True
    assert NET.verify_certificate(rec, {"query_value": True, "bundle_possible": False})[0] is True


def test_12_prompt_lint_after_full_rendering() -> None:
    created = []
    try:
        path = _generate_env("test_epi_prompt_lint", "hard,hard,hard,hard", seed=4)
        created.append(path)
        prompt = (path / "agent" / "workspace" / "prompt.md").read_text(encoding="utf-8")
        assert "%%" not in prompt
        hit = BANNED_WORD.search(prompt)
        assert hit is None, hit
        # Directory-name leak: the source env path contains the stem, the prompt does not.
        assert "gluing" in str(FILES)
        assert re.search(r"\bgluing\b", prompt, re.I) is None
        agent_text = "\n".join(
            p.read_text(errors="ignore")
            for p in (path / "agent" / "workspace").rglob("*")
            if p.is_file()
        )
        hit = BANNED_WORD.search(agent_text.lower())
        assert hit is None, hit
    finally:
        for path in created:
            shutil.rmtree(path, ignore_errors=True)


def _features(model: dict) -> tuple:
    pub = NET.public_model(model)
    return (
        len(pub["agents"]),
        int(pub.get("bundle") is None),
        int(pub.get("nested_bundle") is None),
        int(isinstance(pub["query"], str)),
        len(pub["levels"]),
        len(pub["frames"][pub["levels"][0]]["worlds"]),
    )


def _baseline_local(model: dict) -> bool:
    """Phase-0 B0: predict SAT iff every local cell is nonempty. Ignores intersections."""
    return NET.local_ok(model)


def _baseline_pairwise(model: dict) -> bool:
    """Phase-0 B1: predict SAT iff outer pairwise cells overlap. Ignores 3-wise and nested reports."""
    return NET.pairwise_ok(model)


def test_13_heldout_metrics_and_metadata_probe() -> None:
    dev = {cls: [NET.generate_class(cls, s) for s in NET.DEV_SEEDS] for cls in NET.INSTANCE_CLASSES}
    held = {cls: [NET.generate_class(cls, s) for s in NET.HELD_OUT_SEEDS] for cls in NET.INSTANCE_CLASSES}

    per_class = {}
    for cls, rows in held.items():
        truth = [NET.task_sat(m) for m in rows]
        b0 = [_baseline_local(m) for m in rows]  # local-only predicts SAT iff local_ok
        b1 = [_baseline_pairwise(m) for m in rows]
        bflat = [NET.task_sat(NET.flatten_task_model(m)) for m in rows]
        bk0 = [NET.task_sat(NET.bounded_task_model(m, 0)) for m in rows]
        bk1 = [NET.task_sat(NET.bounded_task_model(m, 1)) for m in rows]
        bk2 = [NET.task_sat(NET.bounded_task_model(m, 2)) for m in rows]
        maj = Counter(truth).most_common(1)[0][0]
        majority = [maj] * len(truth)

        def acc(pred):
            return sum(int(t == p) for t, p in zip(truth, pred)) / len(truth)

        per_class[cls] = {
            "n": len(rows),
            "sat": sum(truth),
            "B0_local": acc(b0),
            "B1_pairwise": acc(b1),
            "Bflat": acc(bflat),
            "Bk0": acc(bk0),
            "Bk1": acc(bk1),
            "Bk2": acc(bk2),
            "majority": acc(majority),
        }
        # Every claimed hard class defeats the shortcut it is designed to defeat.
        if cls == NET.NEG_DEEP:
            assert acc(b1) == 0.0
            assert all(NET.pairwise_ok(m) for m in rows)
            assert all(NET.task_sat(m) is False for m in rows)
        if cls == NET.NEG_RECURSIVE:
            assert acc(bflat) == 0.0
            assert all(NET.task_sat(NET.flatten_task_model(m)) for m in rows)
        if cls == NET.POS_RECURSIVE:
            assert acc(bflat) == 0.0
        if cls == NET.NEG_PAIRWISE:
            assert acc(b1) == 1.0  # pairwise correctly predicts UNSAT
        if cls == NET.NEG_LOCAL:
            assert acc(b0) == 1.0

    # Balanced overall: 30 POS-plain + 30 POS-recursive + 15 of each NEG.
    balanced = []
    balanced += [(m, True) for m in held[NET.POS_PLAIN]]
    balanced += [(m, True) for m in held[NET.POS_RECURSIVE]]
    for cls in (NET.NEG_LOCAL, NET.NEG_PAIRWISE, NET.NEG_DEEP, NET.NEG_RECURSIVE):
        balanced += [(m, False) for m in held[cls][:15]]
    y = [NET.task_sat(m) for m, _ in balanced]
    assert sum(y) == 60 and len(y) - sum(y) == 60

    # Metadata-only: majority SAT per public feature tuple, trained on dev.
    votes: dict[tuple, Counter] = {}
    for cls, rows in dev.items():
        for model in rows:
            votes.setdefault(_features(model), Counter())[NET.task_sat(model)] += 1
    lookup = {feat: counts.most_common(1)[0][0] for feat, counts in votes.items()}
    default = Counter(NET.task_sat(m) for rows in dev.values() for m in rows).most_common(1)[0][0]
    meta_pred = [lookup.get(_features(m), default) for m, _ in balanced]
    meta_acc = sum(int(t == p) for t, p in zip(y, meta_pred)) / len(y)
    per_class["balanced_heldout"] = {
        "n": len(y),
        "sat": sum(y),
        "unsat": len(y) - sum(y),
        "majority_constant": sum(int(t == False) for t in y) / len(y),  # majority on this split is SAT? 60/60
        "metadata_acc": meta_acc,
        "Bflat_acc": sum(
            int(NET.task_sat(m) == NET.task_sat(NET.flatten_task_model(m))) for m, _ in balanced
        )
        / len(y),
        "B1_acc": sum(int(NET.task_sat(m) == _baseline_pairwise(m)) for m, _ in balanced) / len(y),
    }
    # Honest record: metadata may do well; do not tweak features to force failure.
    assert 0.0 <= meta_acc <= 1.0
    report = ROOT / "docs" / "audits" / "2026-10-16-epistemic-heldout-metrics.json"
    report.write_text(json.dumps(per_class, indent=2) + "\n", encoding="utf-8")
    assert per_class[NET.NEG_DEEP]["B1_pairwise"] == 0.0
    assert per_class[NET.NEG_RECURSIVE]["Bflat"] == 0.0
    assert per_class[NET.POS_RECURSIVE]["Bflat"] == 0.0
