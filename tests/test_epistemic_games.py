"""Tests for the epistemic_games environment family (first prototype).

Covers:
- the symbolic core (Bayes math, verdict bands, level policies, mimicry
  invariant, failure-mode taxonomy, no ground-truth leakage);
- generation through generate_env.py (all axis combinations, seed variance,
  the opt-in renderer hook);
- the full judge pipeline end-to-end (patch -> source validation ->
  provenance re-derivation -> isolated answer extraction -> grading),
  driven exactly the way env_runner.py drives it, without Docker or torch.
"""
from __future__ import annotations

import difflib
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "envs" / "epistemic_games"

SCENARIOS = ("trap", "report")
EVIDENCE = ("ambiguous", "weak", "strong")
PRIORS = ("balanced", "skewed")
PRESENTATIONS = ("solo", "paired")

ANSWER_BLOCK = (
    "ANSWER = {\n"
    '    "posterior_world1": None,\n'
    '    "verdict": None,\n'
    '    "most_supported": None,\n'
    '    "justification": None,\n'
    "}"
)


def load_core():
    spec = importlib.util.spec_from_file_location("epg_core", ENV_DIR / "files" / "core.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["epg_core"] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


CORE = load_core()


def run_generate(env: str, name: str, difficulty: str, seed: int, check: bool = True):
    proc = subprocess.run(
        [sys.executable, "generate_env.py", "--env", env, "--name", name,
         "--difficulty", difficulty, "--seed", str(seed)],
        cwd=ROOT, text=True, capture_output=True,
    )
    if check:
        assert proc.returncode == 0, f"generation failed: {proc.stdout}\n{proc.stderr}"
    return proc


def cleanup(*dirs: str) -> None:
    for d in dirs:
        subprocess.run(["rm", "-rf", d], cwd=ROOT)


# ---------------------------------------------------------------------------
# Core: Bayes math and verdict bands
# ---------------------------------------------------------------------------

def test_posterior_and_verdict_recomputed_independently():
    for scenario, evidence, prior, presentation in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS
    ):
        for seed in range(5):
            inst = CORE.build_instance(scenario, evidence, prior, presentation, seed)
            l1, l2 = inst.likelihoods["world1"], inst.likelihoods["world2"]
            pi1 = inst.prior1
            expected_posterior = l1 * pi1 / (l1 * pi1 + l2 * (1 - pi1))
            assert inst.posterior1 == expected_posterior
            ratio = max(l1 / l2, l2 / l1)
            assert inst.likelihood_ratio == ratio
            expected_verdict = (
                "indistinguishable" if ratio == 1
                else "weakly_distinguishable" if ratio < CORE.WEAK_STRONG_RATIO
                else "distinguishable"
            )
            assert inst.verdict == expected_verdict
            p = float(inst.posterior1)
            expected_support = "world1" if p > 0.5 else "world2" if p < 0.5 else "neither"
            assert inst.most_supported == expected_support
            # likelihoods must be readable from the public behavior tables
            assert inst.likelihoods["world1"] == inst.hypotheses["world1"].behavior[inst.observation]
            assert inst.likelihoods["world2"] == inst.hypotheses["world2"].behavior[inst.observation]


def test_known_bayes_values():
    # balanced prior, weak evidence: posterior = L1 / (L1 + L2) with the
    # (1 - evasion, strategic) pair from the evidence table
    pairs = CORE.EVIDENCE_TABLE["weak"]
    for evasion, strategic in pairs:
        denial_expected = (1 - evasion) / (1 - evasion + strategic)
        vague_expected = evasion / (evasion + (1 - strategic))
        # find an instance realizing each observation for this pair
        for observation, expected in (("denial", denial_expected), ("vague", vague_expected)):
            found = False
            for seed in range(300):
                inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed)
                if (
                    inst.hypotheses["world1"].behavior["denial"] == 1 - evasion
                    and inst.hypotheses["world2"].behavior["denial"] == strategic
                    and inst.observation == observation
                ):
                    assert inst.posterior1 == expected, (seed, inst.posterior1, expected)
                    found = True
                    break
            assert found, f"no instance for pair ({evasion}, {strategic}) obs={observation}"


def test_ambiguous_instances_are_observationally_equivalent():
    n = 0
    for scenario, presentation in itertools.product(SCENARIOS, PRESENTATIONS):
        for seed in range(12):
            inst = CORE.build_instance(scenario, "ambiguous", "balanced", presentation, seed)
            assert inst.observational_equivalence
            b1, b2 = inst.hypotheses["world1"].behavior, inst.hypotheses["world2"].behavior
            assert b1 == b2  # identical announcement policies
            assert inst.likelihoods["world1"] == 1 and inst.likelihoods["world2"] == 1
            assert inst.verdict == "indistinguishable"
            assert inst.posterior1 == inst.prior1
            # identical transcripts across the paired worlds
            assert inst.transcript() == inst.transcript()
            assert inst.observation == "denial"
            n += 1
    assert n > 0


def test_level_policies_and_mimicry_invariant():
    assert CORE.level0_action("missed") == "denial"
    assert CORE.level0_action("noticed") == "vague"
    # level 1 (honest, face-value observer) reports the state
    assert CORE.level1_action("missed") == "denial"
    assert CORE.level1_action("noticed") == "vague"
    # level 3 deliberately induces the "missed" reading
    assert CORE.level3_action("noticed", target_state="missed") == "denial"
    # mimicry invariant: level 3 reproduces the level-1 announcement
    CORE.verify_mimicry_invariant(CORE.level1_action("missed"),
                                  CORE.level3_action("noticed", target_state="missed"))
    try:
        CORE.verify_mimicry_invariant("denial", "vague")
    except CORE.InstanceConstructionError:
        pass
    else:
        raise AssertionError("mimicry violation was not detected")


def test_instance_determinism_and_seed_variance():
    a = CORE.build_instance("trap", "weak", "balanced", "paired", 7)
    b = CORE.build_instance("trap", "weak", "balanced", "paired", 7)
    assert a.to_spec() == b.to_spec()
    ta = a.public_task_md()
    tb = CORE.build_instance("trap", "weak", "balanced", "paired", 8).public_task_md()
    assert ta != tb  # surface vocabulary varies with the seed
    tr = CORE.build_instance("report", "weak", "balanced", "paired", 7).public_task_md()
    assert "no issue found" in tr and "trap" not in tr.lower()


def test_no_ground_truth_leakage_in_task():
    for scenario, evidence, prior, presentation in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS
    ):
        for seed in range(4):
            inst = CORE.build_instance(scenario, evidence, prior, presentation, seed)
            task = inst.public_task_md()
            assert "%%" not in task
            # computed values must not appear in the agent-facing text
            assert inst.inference_trace not in task
            assert f"{float(inst.posterior1):.6f}" not in task
            assert f"{float(inst.posterior1):.4f}" not in task
            for phrase in ("correct answer", "ground truth", "actual world", "true world", "reward"):
                assert phrase not in task.lower()
            assert "seed" not in task.lower()


def test_behavior_tables_sum_to_one_and_are_public():
    for scenario in SCENARIOS:
        for evidence in EVIDENCE:
            for seed in range(6):
                inst = CORE.build_instance(scenario, evidence, "balanced", "solo", seed)
                for world in ("world1", "world2"):
                    total = sum(inst.hypotheses[world].behavior.values())
                    assert total == 1
                    for action, prob in inst.hypotheses[world].behavior.items():
                        assert 0 <= prob <= 1
                        # the table is shown to the agent with 2 decimals
                        assert f"{float(prob):.2f}" in inst.public_task_md()


# ---------------------------------------------------------------------------
# Core: grading and failure-mode taxonomy
# ---------------------------------------------------------------------------

def _answer(posterior, verdict, support, justification="Bayes over the behavior tables."):
    return {
        "posterior_world1": posterior,
        "verdict": verdict,
        "most_supported": support,
        "justification": justification,
    }


def test_grade_ground_truth_passes_everywhere():
    for scenario, evidence, prior in itertools.product(SCENARIOS, EVIDENCE, PRIORS):
        inst = CORE.build_instance(scenario, evidence, prior, "paired", seed=11)
        grading = inst.grade(CORE.ground_truth_answer(inst), pass_threshold=0.85)
        assert grading["failure_mode"] == "pass", (
            scenario, evidence, prior, grading
        )
        assert grading["metrics"]["score"] >= 0.85


def test_grade_seductive_truth_and_overcaution():
    inst = CORE.build_instance("trap", "ambiguous", "balanced", "paired", seed=1)
    g = inst.grade(_answer(0.9, "distinguishable", "world1", "they said it, so its true"), 0.85)
    assert g["failure_mode"] == "seductive_truth"
    assert g["metrics"]["score"] < 0.3
    g = inst.grade(_answer(0.1, "distinguishable", "world2", "everything is a trap"), 0.85)
    assert g["failure_mode"] == "overcaution"
    assert g["metrics"]["score"] < 0.3


def test_grade_prior_neglect_on_skewed_ambiguous():
    inst = CORE.build_instance("trap", "ambiguous", "skewed", "paired", seed=1)
    assert inst.posterior1 == Fraction(3, 5)
    assert inst.most_supported == "world1"
    # answering ~0.5 instead of carrying the prior through
    g = inst.grade(_answer(0.5, "indistinguishable", "neither"), 0.85)
    assert g["failure_mode"] == "prior_neglect"
    # correct: the prior carries through unchanged
    g = inst.grade(_answer(0.6, "indistinguishable", "world1"), 0.85)
    assert g["failure_mode"] == "pass"


def test_grade_missed_information_on_weak():
    inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed=1)
    assert inst.verdict != "indistinguishable"
    g = inst.grade(_answer(0.5, "indistinguishable", "neither", "same transcript"), 0.85)
    assert g["failure_mode"] == "missed_information"


def test_grade_wrong_direction():
    # strong evidence with the observed announcement favoring world 2
    def pred(inst):
        return inst.verdict == "distinguishable" and inst.most_supported == "world2"

    inst = None
    for seed in range(300):
        candidate = CORE.build_instance("trap", "strong", "balanced", "paired", seed)
        if pred(candidate):
            inst = candidate
            break
    assert inst is not None, "no world-2-favored strong instance found"
    g = inst.grade(_answer(0.8, "distinguishable", "world1", "trust the genuine type"), 0.85)
    assert g["failure_mode"] == "wrong_direction"


def test_grade_verdict_miscalibration_and_inaccurate_posterior():
    inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed=1)
    true_p = float(inst.posterior1)
    # posterior right, verdict band wrong
    g = inst.grade(_answer(round(true_p, 2), "distinguishable", inst.most_supported), 0.85)
    assert g["failure_mode"] == "verdict_miscalibration"
    # everything right but the magnitude off by a visible amount
    off = 0.7 if true_p < 0.6 else 0.4
    g = inst.grade(_answer(off, inst.verdict, inst.most_supported), 0.85)
    assert g["failure_mode"] == "inaccurate_posterior"
    assert g["metrics"]["score"] < 0.85


def test_grade_format_invalid():
    inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed=1)
    bad_answers = [
        None,
        "not a dict",
        {},
        _answer("hmm", "indistinguishable", "neither"),
        _answer(1.7, "indistinguishable", "neither"),
        _answer(0.5, "strongly", "neither"),
        _answer(0.5, "indistinguishable", "world3"),
        _answer(0.5, "indistinguishable", "neither", justification=""),
        _answer(0.5, "indistinguishable", "neither", justification="x" * 601),
        {**_answer(0.5, "indistinguishable", "neither"), "extra_key": 1},
        _answer(True, "indistinguishable", "neither"),
    ]
    for bad in bad_answers:
        g = inst.grade(bad, 0.85)
        assert g["failure_mode"] == "answer_format_invalid", bad
        assert g["metrics"]["score"] == 0.0
        assert g["checks"]["answer_format_valid"] is False


# ---------------------------------------------------------------------------
# Generation (generate_env.py + renderer hook)
# ---------------------------------------------------------------------------

def test_config_shape():
    config = yaml.safe_load((ENV_DIR / "config.yaml").read_text(encoding="utf-8"))
    assert [ax["id"] for ax in config["axes"]] == ["scenario", "evidence", "presentation", "prior"]
    assert config["scoring"]["mode"] == "continuous_accuracy"
    assert config["renderer"] == "renderer.py"
    registry = yaml.safe_load((ROOT / "envs" / "registry.yaml").read_text(encoding="utf-8"))
    assert registry["environments"]["epistemic_games"] == "envs/epistemic_games/config.yaml"


def test_renderer_hook_missing_file_rejected():
    sys.path.insert(0, str(ROOT))
    import generate_env

    config = yaml.safe_load((ENV_DIR / "config.yaml").read_text(encoding="utf-8"))
    config["renderer"] = "does_not_exist.py"
    try:
        generate_env.validate_config(config, ENV_DIR / "files", "epistemic_games")
    except ValueError as exc:
        assert "renderer" in str(exc)
    else:
        raise AssertionError("missing renderer was not rejected")


def test_renderer_hook_rejects_invalid_placeholder_names():
    sys.path.insert(0, str(ROOT))
    import generate_env

    bad = ENV_DIR / "files" / "_test_bad_renderer.py"
    try:
        bad.write_text("def render(subs):\n    return {'lower_case': 'x', 'GOOD': 'y'}\n", encoding="utf-8")
        try:
            generate_env._run_renderer(ENV_DIR / "files", bad.name, {"SEED": "1"})
        except ValueError as exc:
            assert "placeholder" in str(exc)
        else:
            raise AssertionError("invalid renderer key was accepted")
    finally:
        bad.unlink(missing_ok=True)


def test_smoke_generate_all_combinations():
    for scenario, evidence, presentation, prior in itertools.product(
        SCENARIOS, EVIDENCE, PRESENTATIONS, PRIORS
    ):
        name = f"smoke_eg_{scenario}_{evidence}_{presentation}_{prior}"
        cleanup(name)
        run_generate("epistemic_games", name, f"{scenario},{evidence},{presentation},{prior}", seed=1)
        generated = ROOT / name
        assert generated.exists()
        assert (generated / "run_eval.sh").exists()
        contents = "\n".join(
            p.read_text(errors="ignore") for p in generated.rglob("*") if p.is_file()
        )
        assert not re.search(r"%%[A-Z0-9_]+%%", contents)
        py_files = [str(p) for p in generated.rglob("*.py")]
        assert py_files
        subprocess.run([sys.executable, "-m", "py_compile", *py_files], check=True)
        # the judge-side spec is present and consistent with the axes
        spec_text = (generated / "judge" / "instance_spec.py").read_text(encoding="utf-8")
        assert f"'template': '{scenario}'" in spec_text
        assert f"'evidence': '{evidence}'" in spec_text
        assert f"'presentation': '{presentation}'" in spec_text
        assert f"'prior_id': '{prior}'" in spec_text
        cleanup(name)


def test_seed_varies_surface_across_generations():
    a = f"smoke_eg_seed_a"
    b = f"smoke_eg_seed_b"
    cleanup(a, b)
    run_generate("epistemic_games", a, "trap,weak,paired,balanced", seed=101)
    run_generate("epistemic_games", b, "trap,weak,paired,balanced", seed=102)
    task_a = (ROOT / a / "agent" / "workspace" / "task.md").read_text(encoding="utf-8")
    task_b = (ROOT / b / "agent" / "workspace" / "task.md").read_text(encoding="utf-8")
    assert task_a != task_b
    cleanup(a, b)


# ---------------------------------------------------------------------------
# End-to-end judge (driven the way env_runner.py drives it; no Docker/torch)
# ---------------------------------------------------------------------------

def _generate_judge_env(name: str, difficulty: str, seed: int) -> Path:
    cleanup(name)
    run_generate("epistemic_games", name, difficulty, seed=seed)
    return ROOT / name


def _answer_patch(env_dir: Path, answer: dict) -> str:
    pristine = (env_dir / "agent" / "workspace" / "answer.py").read_text(encoding="utf-8")
    assert ANSWER_BLOCK in pristine, "answer.py template block changed; update ANSWER_BLOCK"
    patched = pristine.replace(ANSWER_BLOCK, "ANSWER = " + json.dumps(answer, indent=4))
    diff = difflib.unified_diff(
        pristine.splitlines(), patched.splitlines(),
        fromfile="a/answer.py", tofile="b/answer.py", lineterm="",
    )
    return "\n".join(diff) + "\n"


def _run_judge(env_dir: Path, patch_text: str, seed: int, label: str) -> dict:
    workdir = ROOT / "smoke_eg_judge_work" / label
    workdir.mkdir(parents=True, exist_ok=True)
    patch_path = workdir / "agent.patch"
    patch_path.write_text(patch_text, encoding="utf-8")
    env = os.environ.copy()
    env["JUDGE_PATCH_PATH"] = str(patch_path)
    env["JUDGE_ORIGINALS_DIR"] = str(env_dir / "agent" / "workspace")
    env["JUDGE_SEED"] = str(seed)
    env["PYTHONPATH"] = str(env_dir / "judge")
    proc = subprocess.run(
        [sys.executable, str(env_dir / "judge" / "judge.py")],
        capture_output=True, text=True, timeout=180, env=env,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"judge printed no result (rc={proc.returncode})\n{proc.stderr}"
    return json.loads(lines[-1])


def test_e2e_judge_correct_answer_passes():
    env_dir = _generate_judge_env("smoke_eg_e2e_ok", "trap,weak,paired,balanced", seed=3)
    try:
        inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed=3)
        result = _run_judge(env_dir, _answer_patch(env_dir, CORE.ground_truth_answer(inst)), 3, "ok")
        assert result["failure_mode"] == "pass"
        assert result["score"] == 1.0
        assert result["checks"]["provenance_ok"] is True
        assert result["metrics"]["posterior_error"] == 0.0
    finally:
        cleanup("smoke_eg_e2e_ok", "smoke_eg_judge_work")


def test_e2e_judge_seductive_answer_diagnosed():
    env_dir = _generate_judge_env("smoke_eg_e2e_sed", "trap,ambiguous,paired,balanced", seed=7)
    try:
        sed = _answer(0.9, "distinguishable", "world1", "A stated it plainly; level 1 tells the truth.")
        result = _run_judge(env_dir, _answer_patch(env_dir, sed), 7, "sed")
        assert result["failure_mode"] == "seductive_truth"
        assert result["score"] < 0.3
        assert result["verdict"] == "FAIL"
    finally:
        cleanup("smoke_eg_e2e_sed", "smoke_eg_judge_work")


def test_e2e_judge_format_invalid_scores_zero():
    env_dir = _generate_judge_env("smoke_eg_e2e_bad", "trap,weak,solo,balanced", seed=5)
    try:
        bad = _answer("yes", "indistinguishable", "neither")
        result = _run_judge(env_dir, _answer_patch(env_dir, bad), 5, "bad")
        assert result["failure_mode"] == "answer_format_invalid"
        assert result["score"] == 0.0
    finally:
        cleanup("smoke_eg_e2e_bad", "smoke_eg_judge_work")


def test_e2e_judge_rejects_tampered_provenance():
    env_dir = _generate_judge_env("smoke_eg_e2e_tamper", "trap,ambiguous,paired,skewed", seed=9)
    spec_path = env_dir / "judge" / "instance_spec.py"
    original = spec_path.read_text(encoding="utf-8")
    try:
        tampered = original.replace("'seed': 9,", "'seed': 900,")
        assert tampered != original
        spec_path.write_text(tampered, encoding="utf-8")
        inst = CORE.build_instance("trap", "ambiguous", "skewed", "paired", seed=9)
        result = _run_judge(env_dir, _answer_patch(env_dir, CORE.ground_truth_answer(inst)), 9, "tamper")
        assert result["failure_mode"] == "reward_denial"
        assert result["score"] == 0.0
    finally:
        spec_path.write_text(original, encoding="utf-8")
        cleanup("smoke_eg_e2e_tamper", "smoke_eg_judge_work")


def test_env_runner_episode_submits_and_scores():
    """Full gym-like loop: reset -> read task -> fill answer -> submit."""
    episode = "pytest_eg_runner"
    subprocess.run(["rm", "-rf", str(ROOT / ".episodes" / episode)], cwd=ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, "env_runner.py", "reset", "--env", "epistemic_games",
             "--episode-id", episode, "--difficulty", "report,ambiguous,paired,balanced",
             "--seed", "42", "--max-steps", "6"],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        state = json.loads(proc.stdout)
        assert state["info"]["required_files"] == ["answer.py"]
        assert state["info"]["patchable_files"] == ["answer.py"]

        proc = subprocess.run(
            [sys.executable, "env_runner.py", "step", "--episode", episode,
             "--action", json.dumps({"type": "read_file", "path": "task.md"})],
            cwd=ROOT, text=True, capture_output=True,
        )
        task = json.loads(proc.stdout)["observation"]
        assert "Type Inference Task" not in task  # paired presentation
        assert "Strategic Ambiguity Task" in task

        inst = CORE.build_instance("report", "ambiguous", "balanced", "paired", seed=42)
        workspace = ROOT / ".episodes" / episode / "env" / "agent" / "workspace"
        pristine = (workspace / "answer.py").read_text(encoding="utf-8")
        filled = pristine.replace(ANSWER_BLOCK, "ANSWER = " + json.dumps(CORE.ground_truth_answer(inst), indent=4))
        proc = subprocess.run(
            [sys.executable, "env_runner.py", "step", "--episode", episode,
             "--action", json.dumps({"type": "write_file", "path": "answer.py", "content": filled})],
            cwd=ROOT, text=True, capture_output=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

        proc = subprocess.run(
            [sys.executable, "env_runner.py", "step", "--episode", episode,
             "--action", json.dumps({"type": "submit"})],
            cwd=ROOT, text=True, capture_output=True, timeout=300,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        data = json.loads(proc.stdout)
        assert data["reward"] == 1.0
        assert data["done"] is True
        result = json.loads(data["observation"])
        assert result["failure_mode"] == "pass"
        assert result["score"] == 1.0
    finally:
        subprocess.run(["rm", "-rf", str(ROOT / ".episodes" / episode)], cwd=ROOT)
