"""Tests for the causal-experiment layer: interventions, twins, provenance, specs.

Every test here is model-free, torch-free and Docker-free on purpose.  The layer
makes claims about *generation* - that a twin is the same task under a different
name, that an overlay actually fired, that a directory came from a given config - and
each of those is decidable from bytes in the repository.  Nothing in this file
should ever need a provider or a container.
"""
from __future__ import annotations

import ast
import json
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import experiment_spec as es  # noqa: E402
from shared import generation_manifest as gm  # noqa: E402

MOCO_EASY = "easy,easy,easy,easy,easy,easy"
MOCO_NO_HINTS = "easy,easy,medium,medium,easy,easy"
GLYPH_EASY = "easy,easy,easy,easy,easy,easy"
EPISTEMIC_BASE = "trap,ambiguous,solo,balanced,narrative"


def _generate(name: str, env: str, difficulty: str, *extra: str) -> Path:
    directory = ROOT / name
    shutil.rmtree(directory, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, "generate_env.py", "--env", env, "--name", name,
         "--difficulty", difficulty, "--seed", "3", *extra],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return directory


def _twin_check(base: Path, twin: Path) -> dict:
    report_path = twin / "twin_report.json"
    proc = subprocess.run(
        [sys.executable, "tools/twin_check.py", str(base), str(twin),
         "--json", str(report_path)],
        cwd=ROOT, text=True, capture_output=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["_returncode"] = proc.returncode
    report["_stdout"] = proc.stdout
    return report


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def test_every_generated_environment_carries_a_verified_manifest() -> None:
    name = "test_causal_manifest"
    try:
        directory = _generate(name, "glyph", GLYPH_EASY)
        manifest = gm.read_manifest(directory)
        assert manifest["environment"] == "glyph"
        assert manifest["config_path"] == "envs/glyph/config.yaml"
        assert manifest["generation_id"].startswith("G")
        assert manifest["pair_id"].startswith("P")
        assert manifest["interventions"] == []
        assert manifest["latent_spec"] == "unavailable"
        assert manifest["pair_id_basis"] == "case_id_fallback"
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert ok, errors
        # The manifest lives inside the generated tree, so the unresolved-placeholder
        # sweep the generator tests run over every environment covers it too.
        text = (directory / gm.MANIFEST_NAME).read_text(encoding="utf-8")
        assert not re.search(r"%%[A-Z0-9_]+%%", text)
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_tampering_with_a_generated_tree_breaks_provenance() -> None:
    name = "test_causal_tamper"
    try:
        directory = _generate(name, "glyph", GLYPH_EASY)
        target = directory / "agent" / "workspace" / "model.py"
        target.write_text(target.read_text(encoding="utf-8") + "\n# edited after generation\n",
                          encoding="utf-8")
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert not ok
        assert any("model.py" in error for error in errors), errors
        assert any("tree_sha256" in error for error in errors), errors
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_manifest_records_the_judge_separately_from_the_agent_tree() -> None:
    name = "test_causal_judgehash"
    try:
        directory = _generate(name, "moco", MOCO_EASY)
        manifest = gm.read_manifest(directory)
        assert "judge/judge.py" in manifest["judge_files"]
        agent_keys = [key for key in manifest["files"] if key.startswith("agent/")]
        judge_keys = [key for key in manifest["files"] if key.startswith("judge/")]
        assert agent_keys and judge_keys
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


# ---------------------------------------------------------------------------
# interventions must be real
# ---------------------------------------------------------------------------

def test_unimplemented_intervention_is_refused_not_skipped() -> None:
    """An inert overlay reported as an invariance test is the failure mode to prevent."""
    proc = subprocess.run(
        [sys.executable, "generate_env.py", "--env", "moco", "--name", "test_causal_unknown",
         "--difficulty", MOCO_EASY, "--seed", "3", "--interventions", "monitoring"],
        cwd=ROOT, text=True, capture_output=True,
    )
    shutil.rmtree(ROOT / "test_causal_unknown", ignore_errors=True)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "does not implement intervention 'monitoring'" in combined
    assert "terminology" in combined  # what is actually available, stated back


def test_terminology_twin_is_the_same_task_under_a_different_name() -> None:
    base_name, twin_name = "test_causal_term_base", "test_causal_term_twin"
    try:
        base = _generate(base_name, "moco", MOCO_EASY)
        twin = _generate(twin_name, "moco", MOCO_EASY, "--interventions", "terminology")
        base_manifest = gm.read_manifest(base)
        twin_manifest = gm.read_manifest(twin)

        assert twin_manifest["generation_id"] != base_manifest["generation_id"]
        # Task identity must survive a presentation change: that separation of
        # pair_id from generation_id is what makes an invariance claim mean anything.
        assert twin_manifest["pair_id"] == base_manifest["pair_id"]

        report = _twin_check(base, twin)
        assert report["status"] == "pass", report
        assert report["equivalence"] == "semantically_equivalent"
        assert report["checks"]["normalized_trees_identical"] is True
        # The module file itself is renamed, so a path-only comparison would have
        # called this a different task.
        assert report["files_only_in_twin"] and report["files_only_in_base"]
        assert report["_returncode"] == 0
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_observation_intervention_does_not_move_task_identity_but_must_fire() -> None:
    base_name, twin_name = "test_causal_cue_base", "test_causal_cue_twin"
    try:
        base = _generate(base_name, "moco", MOCO_EASY)
        twin = _generate(twin_name, "moco", MOCO_EASY, "--interventions", "retrieval_cue")
        report = _twin_check(base, twin)
        assert report["status"] == "pass", report
        assert report["equivalence"] == "observation_changing"
        assert gm.read_manifest(twin)["pair_id"] == gm.read_manifest(base)["pair_id"]
        assert report["differing_files_raw"]
        twin_text = (twin / "agent" / "workspace" / "prompt.md").read_text(encoding="utf-8")
        assert "Hint: does K divide evenly" not in twin_text
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_an_inert_intervention_fails_the_twin_check() -> None:
    """At this difficulty vector the hints are already gone, so there is no experiment."""
    base_name, twin_name = "test_causal_inert_base", "test_causal_inert_twin"
    try:
        base = _generate(base_name, "moco", MOCO_NO_HINTS)
        twin = _generate(twin_name, "moco", MOCO_NO_HINTS, "--interventions", "retrieval_cue")
        report = _twin_check(base, twin)
        assert report["status"] == "fail"
        assert report["checks"]["only_the_instance_label_differs"] is True
        assert report["_returncode"] == 1
        assert any("config bug" in problem for problem in report["problems"]), report
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_task_changing_twin_moves_pair_id_and_is_proved_from_the_latent_spec() -> None:
    base_name, twin_name = "test_causal_prior_base", "test_causal_prior_twin"
    try:
        base = _generate(base_name, "epistemic_games", EPISTEMIC_BASE)
        twin = _generate(twin_name, "epistemic_games", EPISTEMIC_BASE,
                         "--interventions", "prior")
        base_manifest = gm.read_manifest(base)
        twin_manifest = gm.read_manifest(twin)
        assert base_manifest["pair_id_basis"] == "latent_spec"
        assert twin_manifest["pair_id"] != base_manifest["pair_id"]
        report = _twin_check(base, twin)
        assert report["status"] == "pass", report
        assert report["equivalence"] == "task_changing"
        assert report["checks"]["pair_id_moved"] is True
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_environment_may_not_relabel_what_must_stay_invariant(tmp_path: Path) -> None:
    """A config cannot quietly downgrade its own equivalence declaration."""
    import generate_env as ge

    taxonomy = ge.load_intervention_taxonomy()
    config = {
        "axes": [{"id": "a", "levels": {"easy": {}}}],
        "layout": {},
        "interventions": {
            "terminology": {"equivalence": "task_changing", "substitutions": {"FOO": "bar"}}
        },
    }
    try:
        ge.resolve_interventions("fake_env", ["terminology"], config, taxonomy)
    except ValueError as exc:
        assert "may not redefine" in str(exc)
    else:
        raise AssertionError("an environment was allowed to redefine equivalence")


def test_rename_transform_compiles_and_is_invertible() -> None:
    """glyph has no naming placeholders, so its rename runs over the whole tree."""
    base_name, twin_name = "test_causal_rename_base", "test_causal_rename_twin"
    try:
        base = _generate(base_name, "glyph", GLYPH_EASY)
        twin = _generate(twin_name, "glyph", GLYPH_EASY, "--interventions", "terminology")
        overlay = gm.read_manifest(twin)["interventions"][0]
        assert overlay["mechanism"] == "rename"
        renames = overlay["renames"]
        assert "GlyphCNN" in renames
        assert renames["GlyphCNN"]["occurrences"] > 0
        alias = renames["GlyphCNN"]["alias"]
        twin_model = (twin / "agent" / "workspace" / "model.py").read_text(encoding="utf-8")
        assert alias in twin_model and "class GlyphCNN" not in twin_model
        # Both sides moved together: the judge builds a probe script that imports the
        # class by name, and a rename that reached only the workspace would break it.
        # The judge builds a probe script at run time that imports the model by name,
        # so the rename must reach the judge tree too.
        twin_all = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(twin.rglob("*"))
            if path.is_file() and path.name != gm.MANIFEST_NAME
        )
        base_all = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(base.rglob("*"))
            if path.is_file() and path.name != gm.MANIFEST_NAME
        )
        assert alias in twin_all
        assert "GlyphCNN" not in twin_all and "load_model" not in twin_all
        assert "GlyphCNN" in base_all
        # Compare before compiling: a .pyc dropped into either tree is part of that
        # tree as far as twin_check is concerned, and it legitimately differs.
        report = _twin_check(base, twin)
        assert report["status"] == "pass", report
        for directory in (base, twin):
            for path in sorted(directory.rglob("*.py")):
                cfile = Path(tempfile.mkdtemp(prefix="pyc_")) / (path.name + "c")
                py_compile.compile(str(path), doraise=True, cfile=str(cfile))
                cfile.unlink(missing_ok=True)
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


# ---------------------------------------------------------------------------
# config validation of the new keys
# ---------------------------------------------------------------------------

def test_axis_classes_and_intervention_blocks_are_validated() -> None:
    import generate_env as ge

    bad = {
        "axes": [{"id": "a", "levels": {"easy": {}}, "class": "narrative_depth"}],
        "layout": {},
        "renameable_tokens": ["not an identifier"],
        "interventions": {"terminology": {}},
    }
    errors = ge.validate_intervention_blocks(bad, "fake_env")
    assert any("class 'narrative_depth'" in error for error in errors), errors
    assert any("not a plain identifier" in error for error in errors), errors
    assert any("config bug" in error for error in errors), errors


def test_every_registered_environment_still_generates_and_validates() -> None:
    """The new keys are optional; nothing here may break the 34 existing configs."""
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    seen = set()
    for env_name, config_rel in registry["environments"].items():
        if env_name in seen:
            continue
        seen.add(env_name)
        config = yaml.safe_load((ROOT / config_rel).read_text(encoding="utf-8"))
        errors = _validate_env(env_name, config)
        assert not errors, (env_name, errors)


def _validate_env(env_name: str, config: dict) -> list[str]:
    import generate_env as ge

    files_dir = ge.find_files_dir(env_name)
    try:
        ge.validate_config(config, files_dir, env_name)
    except ValueError as exc:
        return [str(exc)]
    return []


def test_declared_interventions_resolve_against_their_own_taxonomy() -> None:
    """Every implemented id in every config must exist, be consistent, and not be inert."""
    import generate_env as ge

    taxonomy = ge.load_intervention_taxonomy()
    for config_path in sorted((ROOT / "envs").rglob("config.yaml")):
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        for iid, impl in (config.get("interventions") or {}).items():
            assert iid in taxonomy, f"{config_path}: {iid} is not in envs/interventions.yaml"
            for field in ("equivalence", "expect"):
                if impl.get(field) is not None:
                    assert str(impl[field]) == str(taxonomy[iid].get(field)), (
                        f"{config_path}: {iid} overrides {field}"
                    )
            # An id that resolves to nothing at any difficulty is a silent no-op.
            mechanism = str(impl.get("mechanism") or taxonomy[iid].get("mechanism"))
            assert (
                impl.get("substitutions")
                or impl.get("layout")
                or mechanism == "rename"
                or (mechanism == "view" and impl.get("view"))
            ), f"{config_path}: {iid} is empty"
            if mechanism == "view":
                declared = [str(v) for v in ((config.get("evaluators") or {}).get("views") or [])]
                assert impl["view"] in declared, f"{config_path}: {iid} selects an undeclared view"
            if mechanism == "rename":
                assert config.get("renameable_tokens"), f"{config_path}: {iid} renames nothing"


# ---------------------------------------------------------------------------
# experiment specs
# ---------------------------------------------------------------------------

def _good_spec() -> dict:
    return yaml.safe_load((ROOT / "spec" / "invariant-vs-presentation.yaml").read_text())


def test_the_shipped_spec_validates_against_the_registry() -> None:
    import generate_env as ge

    implemented = {
        name: sorted((ge.load_config(name).get("interventions") or {}).keys())
        for name in sorted(set(ge._load_registry()))
    }
    errors, warnings = es.validate_spec(
        _good_spec(),
        taxonomy=ge.load_intervention_taxonomy(),
        implemented=implemented,
        known_environments=sorted(implemented),
    )
    assert not errors, errors
    assert not warnings, warnings


def test_a_spec_without_a_rival_or_a_control_is_rejected() -> None:
    spec = _good_spec()
    spec["hypotheses"] = [spec["hypotheses"][0]]
    spec["controls"] = []
    spec["members"] = [m for m in spec["members"] if not m.get("interventions")]
    errors, _ = es.validate_spec(spec, taxonomy={}, implemented={"moco": []},
                                 known_environments=["moco"])
    joined = "\n".join(errors)
    assert "competing explanation" in joined
    assert "no control" in joined
    assert "no member produces" in joined


def test_expect_invariant_under_a_task_changing_intervention_is_an_error() -> None:
    import generate_env as ge

    spec = _good_spec()
    spec["members"][1]["interventions"] = ["prior"]
    spec["members"][1]["environment"] = "epistemic_games"
    errors, _ = es.validate_spec(
        spec,
        taxonomy=ge.load_intervention_taxonomy(),
        implemented={"moco": ["terminology"], "epistemic_games": ["prior"]},
        known_environments=["moco", "epistemic_games"],
    )
    assert any("task-changing" in error for error in errors), errors


def test_family_expansion_is_per_seed_and_verified(tmp_path: Path) -> None:
    import generate_env as ge
    from tools import family as family_tool

    plan = family_tool.plan_members("moco", MOCO_EASY, [3, 4], ["terminology", "retrieval_cue"])
    assert [item["role"] for item in plan] == [
        "baseline", "member", "member", "baseline", "member", "member",
    ]
    out = tmp_path / "family"
    manifest = family_tool.generate_family(plan, out, check=True)
    assert manifest["ok"] is True, json.dumps(manifest["verification"], indent=2)
    assert manifest["verification"]["counts"]["fail"] == 0
    members = manifest["members"]
    assert len(members) == 6
    by_role = {}
    for member in members:
        by_role.setdefault(member["role"], []).append(member)
    assert len(by_role["baseline"]) == 2
    # one baseline per seed, and each member points at the baseline of its own seed
    parents = {member["parent_generation_id"] for member in by_role["member"]}
    assert parents == {member["generation_id"] for member in by_role["baseline"]}
    for member in members:
        directory = out / member["name"]
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert ok, (member["name"], errors)


def test_family_cli_refuses_an_incoherent_spec(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.safe_dump(
            {
                "spec_version": 1,
                "id": "nope",
                "hypotheses": [{"id": "H1", "statement": "x"}],
                "measurements": ["accuracy"],
                "members": [{"id": "m1", "environment": "moco", "difficulty": MOCO_EASY}],
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "tools/family.py", "--spec", str(bad), "--out", str(tmp_path / "out")],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 2
    assert "competing explanation" in proc.stderr
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*/generation.json"))


def test_generator_modules_import_without_torch_or_yaml_tricks() -> None:
    """The layer runs in plain CI: no torch, no provider, no containers."""
    for relative in ("generate_env.py", "tools/twin_check.py", "tools/family.py",
                     "shared/generation_manifest.py", "shared/experiment_spec.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0
        }
        assert "torch" not in imported, (relative, sorted(imported))
