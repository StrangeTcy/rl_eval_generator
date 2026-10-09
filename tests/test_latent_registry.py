"""Tests for the latent registry (item 4, PR-C): latent_factors, latent_spec.json, pair_id.

The promotion this layer makes is the decision's own words: ``pair_id`` stops being
the case id and becomes the hash of the spec's identity projection, so twins that
differ only in prose finally pair instead of looking like different tasks - and a
task-changing overlay has to move that projection *structurally*, which is what
``tools/twin_check.py`` is then able to prove instead of trust.

Model-free, torch-free, Docker-free like the rest of the causal layer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared import generation_manifest as gm  # noqa: E402
from shared import latent_spec as ls  # noqa: E402
from tools.latent_factors_scaffold import build_block, classify_placeholder  # noqa: E402

MOCO_EASY = "easy,easy,easy,easy,easy,easy"
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


def _spec(directory: Path) -> dict:
    return json.loads((directory / ls.SPEC_NAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# registry completeness
# ---------------------------------------------------------------------------

def test_every_registry_config_declares_a_valid_latent_factors_block() -> None:
    proc = subprocess.run(
        [sys.executable, "tools/latent_factors_scaffold.py", "--check"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    paths = {str(path) for path in registry["environments"].values()}
    # Count-agnostic on purpose: the registry grows as environments are added
    # (34 at PR-C.1, 39 after the epistemic-semantics families were ported in).
    # What must hold is that *every* config validates, so the scaffold reports
    # N/N for however many N configs the registry currently has.
    assert f"{len(paths)}/{len(paths)}" in proc.stdout, proc.stdout
    stamped = 0
    for relative in sorted(paths):
        config = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
        block = config["latent_factors"]
        assert block["declared_by"] in ls.DECLARED_BY, relative
        assert "evaluator_state" in block["factors"], relative
        assert "task_state" in block["factors"], relative
        if block["declared_by"] == "scaffold_unreviewed":
            stamped += 1
    # Exactly one hand-authored projection (epistemic_games); every other block
    # is scaffold output awaiting review - the stamp is what keeps a mechanical
    # declaration from being cited as a causal claim.
    assert stamped == len(paths) - 1


def test_scaffold_rules_are_the_documented_precedence() -> None:
    # patterns beat axis tags: a planted cue inside a task axis stays out of identity
    assert classify_placeholder("queue_math", "task", "QUEUE_HINT") == ("observable_state", "pattern:cue-text")
    assert classify_placeholder("visible_tests", "observation", "EXTRA_TESTS") == ("proxy_signal", "pattern:TEST")
    # tags are next
    assert classify_placeholder("architecture", "task", "ARCH_EXTRA_CLASS") == ("task_state", "axis_class:task")
    assert classify_placeholder("naming", "presentation", "MODEL_CLASS") == ("observable_state", "axis_class:presentation")
    # then untagged axis ids in registry idiom
    assert classify_placeholder("naming", None, "MODEL_CLASS") == ("observable_state", "axis_id:naming")
    assert classify_placeholder("representation", None, "SPEC_TEXT") == ("observable_state", "axis_id:representation")
    # then untagged naming-shaped placeholders
    assert classify_placeholder("hidden_depth", None, "ANGLE_VAR") == ("observable_state", "pattern:naming-shape")
    # conservative default
    assert classify_placeholder("hidden_depth", None, "STRING_LEN") == ("task_state", "default:task_state")


def test_scaffold_block_validates_and_is_idempotent() -> None:
    config = yaml.safe_load((ROOT / "envs" / "moco" / "config.yaml").read_text(encoding="utf-8"))
    # moco already carries its (scaffold-shaped, appended) block; rebuilding the
    # block from the same config must produce the same declaration.
    fresh = yaml.safe_load((ROOT / "envs" / "glyph" / "config.yaml").read_text(encoding="utf-8"))
    block = build_block(fresh)
    rendered = yaml.safe_load(
        "\n".join(
            line for line in subprocess.run(
                [sys.executable, "tools/latent_factors_scaffold.py", "--env", "glyph"],
                cwd=ROOT, text=True, capture_output=True,
            ).stdout.splitlines()
            if not line.startswith("# ----")
        )
    )
    assert rendered["latent_factors"]["factors"] == block["factors"]
    assert ls.validate_latent_factors({"axes": fresh["axes"], "constants": fresh.get("constants"),
                                       "latent_factors": block}, "glyph") == []
    assert config["latent_factors"]["factors"]["task_state"]["placeholders"] == [
        "BATCH_SIZE", "DROP_LAST", "K", "TEMP_HELPER", "TEMP_K", "TEMP_Q",
    ]


def test_validator_refuses_the_ways_a_block_can_lie() -> None:
    base = {
        "axes": [{"id": "a", "levels": {"easy": {"%%FOO%%": "x"}}}],
        "latent_factors": {
            "schema_version": 1,
            "declared_by": "scaffold_unreviewed",
            "factors": {
                "task_state": {"placeholders": ["FOO"]},
                "evaluator_state": {"scoring": True},
            },
        },
    }
    assert ls.validate_latent_factors(base, "env") == []
    assert any("missing" in e for e in ls.validate_latent_factors({"axes": base["axes"]}, "env"))

    bad_stamp = json.loads(json.dumps(base))
    bad_stamp["latent_factors"]["declared_by"] = "model_guess"
    assert any("declared_by" in e for e in ls.validate_latent_factors(bad_stamp, "env"))

    no_evaluator = json.loads(json.dumps(base))
    del no_evaluator["latent_factors"]["factors"]["evaluator_state"]
    errors = ls.validate_latent_factors(no_evaluator, "env")
    assert any("evaluator_state" in e and "collide" in e for e in errors)

    doubled = json.loads(json.dumps(base))
    doubled["latent_factors"]["factors"]["observable_state"] = {"placeholders": ["FOO"]}
    assert any("already declared" in e for e in ls.validate_latent_factors(doubled, "env"))

    phantom = json.loads(json.dumps(base))
    phantom["latent_factors"]["factors"]["task_state"]["placeholders"] = ["NOT_A_VALUE"]
    assert any("appears in no axis level" in e for e in ls.validate_latent_factors(phantom, "env"))

    silent = json.loads(json.dumps(base))
    silent["latent_factors"]["factors"]["causal_mechanism"] = {ls.UNAVAILABLE: ""}
    assert any("reason" in e for e in ls.validate_latent_factors(silent, "env"))

    ungrounded = json.loads(json.dumps(base))
    ungrounded["latent_factors"]["factors"]["task_state"] = {
        "source": "instance_spec", "identity_keys": ["nope"],
    }
    assert any("requires a renderer" in e for e in ls.validate_latent_factors(ungrounded, "env"))


# ---------------------------------------------------------------------------
# the derived artifact
# ---------------------------------------------------------------------------

def test_generated_tree_carries_the_spec_outside_the_agent_workspace() -> None:
    name = "test_latent_spec_shape"
    try:
        directory = _generate(name, "glyph", GLYPH_EASY)
        manifest = gm.read_manifest(directory)
        assert manifest["latent_spec"] == "declared"
        assert manifest["pair_id_basis"] == "latent_spec"
        assert manifest["latent_spec_declared_by"] == "scaffold_unreviewed"
        assert manifest["pair_id"] == "P" + manifest["latent_spec_sha256"][:16]
        spec = _spec(directory)
        assert spec["environment"] == "glyph"
        assert spec["identity"]["sha256"] == manifest["latent_spec_sha256"]
        assert ls.recompute_identity_sha256(spec) == spec["identity"]["sha256"]
        # the spec is host-side: the agent container never sees it
        assert not list((directory / "agent").rglob(ls.SPEC_NAME))
        # unavailable factors are recorded with reasons, never dropped
        mechanism = spec["factors"]["causal_mechanism"]
        assert set(mechanism) == {ls.UNAVAILABLE} and mechanism[ls.UNAVAILABLE]
        assert set(spec["factors"]["agent_belief"]) == {ls.UNAVAILABLE}
        assert any("not a causal model" in note for note in spec["notes"])
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert ok, errors
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_spec_derivation_is_deterministic() -> None:
    name_a, name_b = "test_latent_determinism_a", "test_latent_determinism_b"
    try:
        a = _generate(name_a, "moco", MOCO_EASY)
        b = _generate(name_b, "moco", MOCO_EASY)
        spec_a = (a / ls.SPEC_NAME).read_bytes()
        spec_b = (b / ls.SPEC_NAME).read_bytes()
        # The instance label differs between the trees, but the spec must not:
        # it is a function of (config, vector, seed, interventions) only.
        assert spec_a == spec_b
    finally:
        shutil.rmtree(ROOT / name_a, ignore_errors=True)
        shutil.rmtree(ROOT / name_b, ignore_errors=True)


# ---------------------------------------------------------------------------
# pair relations across the four equivalence classes
# ---------------------------------------------------------------------------

def test_presentation_twin_keeps_identity_through_composed_values() -> None:
    base_name, twin_name = "test_latent_term_base", "test_latent_term_twin"
    try:
        base = _generate(base_name, "moco", MOCO_EASY)
        twin = _generate(twin_name, "moco", MOCO_EASY, "--interventions", "terminology")
        base_spec, twin_spec = _spec(base), _spec(twin)
        assert twin_spec["identity"]["sha256"] == base_spec["identity"]["sha256"]
        assert gm.read_manifest(twin)["pair_id"] == gm.read_manifest(base)["pair_id"]
        # The raw record still shows the instance as generated: the renamed module
        # reached the judge-side allowlist, and the identity digest canonicalized it
        # back through the declared renaming rather than ignoring it.
        twin_constants = twin_spec["factors"]["evaluator_state"]["constants"]
        assert "retrieval_pooled_encoder.py" in twin_constants["PATCHABLE_FILES"]
        base_constants = base_spec["factors"]["evaluator_state"]["constants"]
        assert "moco_model.py" in base_constants["PATCHABLE_FILES"]
        # presentation dress is recorded where it belongs: observable, never identity
        assert twin_spec["factors"]["observable_state"]["MODEL_CLASS"] == "RetrievalPooledEncoder"
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_observation_and_proxy_twins_record_the_move_without_splitting_the_pair() -> None:
    base_name, cue_name, proxy_name = (
        "test_latent_obs_base", "test_latent_obs_cue", "test_latent_obs_proxy",
    )
    try:
        base = _generate(base_name, "moco", MOCO_EASY)
        cue = _generate(cue_name, "moco", MOCO_EASY, "--interventions", "retrieval_cue")
        proxy = _generate(proxy_name, "moco", MOCO_EASY, "--interventions", "visible_proxy")
        base_pair = gm.read_manifest(base)["pair_id"]
        assert gm.read_manifest(cue)["pair_id"] == base_pair
        assert gm.read_manifest(proxy)["pair_id"] == base_pair
        cue_spec, proxy_spec = _spec(cue), _spec(proxy)
        assert cue_spec["factors"]["observable_state"]["QUEUE_HINT"] == ""
        assert _spec(base)["factors"]["observable_state"]["QUEUE_HINT"] != ""
        assert "MISLEADING" in proxy_spec["factors"]["proxy_signal"]["VISIBLE_TEST_BODY"]
        # identity digests are untouched by both
        assert cue_spec["identity"]["sha256"] == _spec(base)["identity"]["sha256"]
        assert proxy_spec["identity"]["sha256"] == _spec(base)["identity"]["sha256"]
    finally:
        for name in (base_name, cue_name, proxy_name):
            shutil.rmtree(ROOT / name, ignore_errors=True)


def test_view_twin_spec_is_byte_identical_to_its_baseline() -> None:
    base_name, twin_name = "test_latent_view_base", "test_latent_view_twin"
    try:
        base = _generate(base_name, "moco", MOCO_EASY)
        twin = _generate(twin_name, "moco", MOCO_EASY, "--interventions", "evaluator")
        # A measurement change must change no byte of the artifact - the spec included,
        # since the selected view lives in generation.json, not in the task record.
        assert (twin / ls.SPEC_NAME).read_bytes() == (base / ls.SPEC_NAME).read_bytes()
        assert gm.read_manifest(twin)["pair_id"] == gm.read_manifest(base)["pair_id"]
        assert gm.read_manifest(twin)["authoritative_view"] == "behavioral_gated"
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_task_overlay_moves_the_projection_structurally() -> None:
    base_name, twin_name = "test_latent_prior_base", "test_latent_prior_twin"
    try:
        base = _generate(base_name, "epistemic_games", EPISTEMIC_BASE)
        twin = _generate(twin_name, "epistemic_games", EPISTEMIC_BASE,
                         "--interventions", "prior")
        base_spec, twin_spec = _spec(base), _spec(twin)
        assert twin_spec["identity"]["sha256"] != base_spec["identity"]["sha256"]
        assert gm.read_manifest(twin)["pair_id"] != gm.read_manifest(base)["pair_id"]
        projection = twin_spec["factors"]["task_state"]["instance_spec"]
        assert projection["prior_id"] == "skewed"
        assert base_spec["factors"]["task_state"]["instance_spec"]["prior_id"] == "balanced"
        # the projection is the Bayesian core, not the dressed-up file
        assert "framing" not in projection and "template" not in projection
        assert "transcript" not in projection
    finally:
        shutil.rmtree(ROOT / base_name, ignore_errors=True)
        shutil.rmtree(ROOT / twin_name, ignore_errors=True)


def test_prose_twins_are_one_task() -> None:
    """The property item 13 exists for: framing and scenario dress do not split pairs."""
    names = ["test_latent_prose_base", "test_latent_prose_bare", "test_latent_prose_report"]
    try:
        base = _generate(names[0], "epistemic_games", EPISTEMIC_BASE)
        bare = _generate(names[1], "epistemic_games", "trap,ambiguous,solo,balanced,bare_table")
        report = _generate(names[2], "epistemic_games", "report,ambiguous,solo,balanced,narrative")
        pair = gm.read_manifest(base)["pair_id"]
        assert gm.read_manifest(bare)["pair_id"] == pair
        assert gm.read_manifest(report)["pair_id"] == pair
        # ... while the trees really do differ, so this is a merge, not a no-op
        assert (bare / "agent" / "workspace" / "task.md").read_bytes() != (
            base / "agent" / "workspace" / "task.md"
        ).read_bytes()
        # and a different seed is still a different draw of the task
        other_seed_dir = ROOT / "test_latent_prose_seed"
        shutil.rmtree(other_seed_dir, ignore_errors=True)
        proc = subprocess.run(
            [sys.executable, "generate_env.py", "--env", "epistemic_games",
             "--name", "test_latent_prose_seed", "--difficulty", EPISTEMIC_BASE, "--seed", "4"],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert gm.read_manifest(other_seed_dir)["pair_id"] != pair
        shutil.rmtree(other_seed_dir, ignore_errors=True)
    finally:
        for name in names:
            shutil.rmtree(ROOT / name, ignore_errors=True)


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

def test_tampering_with_the_spec_is_caught_where_it_happens() -> None:
    name = "test_latent_tamper"
    try:
        directory = _generate(name, "moco", MOCO_EASY)

        # editing the raw factor text is a tree edit: files map and tree hash catch it
        spec_path = directory / ls.SPEC_NAME
        original = spec_path.read_text(encoding="utf-8")
        spec_path.write_text(original.replace('"512"', '"513"'), encoding="utf-8")
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert not ok
        assert any(ls.SPEC_NAME in error or "tree_sha256" in error for error in errors)

        # editing the identity payload is an identity claim: the recomputation catches it
        spec_path.write_text(original, encoding="utf-8")
        spec = json.loads(original)
        spec["identity"]["payload"]["seed"] = 99
        spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert not ok
        assert any("latent_spec_sha256 does not match" in error for error in errors), errors

        # deleting the spec removes the pair's grounding entirely
        spec_path.unlink()
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert not ok
        assert any("missing" in error and ls.SPEC_NAME in error for error in errors), errors
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_legacy_manifests_without_a_spec_still_verify_on_the_fallback() -> None:
    """Pre-PR-C artifacts keep their recorded identity; the fallback branch is frozen."""
    pid, basis = gm.pair_id(
        env="moco", seed=3,
        difficulty_vector={"a": "easy"},
        intervention_vector=[],
        latent_spec_sha256=None,
    )
    assert basis == "case_id_fallback" and pid.startswith("P")
    promoted, promoted_basis = gm.pair_id(
        env="moco", seed=3,
        difficulty_vector={"a": "easy"},
        intervention_vector=[],
        latent_spec_sha256="ab" * 32,
    )
    assert promoted_basis == "latent_spec"
    assert promoted == "P" + ("ab" * 32)[:16]
