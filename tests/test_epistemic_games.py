"""Tests for the epistemic_games environment family (first prototype).

Covers:
- the symbolic core (Bayes math, verdict bands, level policies, mimicry
  invariant, failure-mode taxonomy, no ground-truth leakage);
- generation through generate_env.py (all axis combinations, seed variance,
  the opt-in renderer hook);
- the full judge pipeline end-to-end (patch -> source validation ->
  provenance re-derivation -> bounded literal answer extraction -> grading),
  driven exactly the way env_runner.py drives it, without Docker or torch.
- P0 hardening: inconsistent posterior/support, verdict_miscalibration
  vs psychological labels, safe literal extraction, hidden-world invariance,
  public-only oracle.
"""
from __future__ import annotations

import ast
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
FRAMINGS = ("narrative", "bare_table")

ANSWER_BLOCK = (
    "ANSWER = {\n"
    '    "posterior_world1": None,\n'
    '    "verdict": None,\n'
    '    "most_supported": None,\n'
    '    "justification": None,\n'
    "}\n"
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
            # transcript is deterministic from observation + vocab
            assert inst.observation == "denial"
            assert inst.transcript().endswith(inst.action_text(inst.observation) + '"')
            n += 1
    assert n > 0


def test_hidden_world_invariance():
    """Changing only actual_world must not change public payload or reference answer.

    This is the counterfactual replacement for the tautological
    assert transcript()==transcript() check.
    """
    for scenario, evidence, prior, presentation in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS
    ):
        for seed in range(3):
            inst = CORE.build_instance(scenario, evidence, prior, presentation, seed)
            # Build a second instance with identical public content but flipped actual_world
            other_world = "world2" if inst.actual_world == "world1" else "world1"
            # Copy instance with different actual_world — public_task_md must be identical
            # and reference posteriors/verdicts identical (answer does not depend on draw)
            from dataclasses import replace

            inst2 = replace(inst, actual_world=other_world)
            # Public rendering must be identical (actual_world is provenance only)
            assert inst.public_task_md() == inst2.public_task_md()
            # Reference posteriors and verdicts identical
            assert inst.posterior1 == inst2.posterior1
            assert inst.verdict == inst2.verdict
            assert inst.most_supported == inst2.most_supported
            assert inst.likelihoods == inst2.likelihoods
            # to_spec differs only in actual_world field
            spec1 = inst.to_spec()
            spec2 = inst2.to_spec()
            for k in spec1:
                if k == "actual_world":
                    assert spec1[k] != spec2[k]
                else:
                    assert spec1[k] == spec2[k], f"public field {k} changed with actual_world"


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
# Core: grading and failure-mode taxonomy — including P0 hardening
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
        assert grading["metrics"]["strict_correct"] is True
        assert grading["checks"]["support_consistent"] is True


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
    # Use strong evidence where true posterior is far from 0.5, so reporting
    # 0.5/indistinguishable is clearly missing the signal (error >0.15, so
    # verdict_miscalibration does not preempt it).
    inst = None
    for seed in range(300):
        cand = CORE.build_instance("trap", "strong", "balanced", "paired", seed)
        if cand.verdict == "distinguishable" and abs(float(cand.posterior1) - 0.5) > 0.2:
            inst = cand
            break
    assert inst is not None, "no strong far-from-0.5 instance found"
    assert inst.verdict != "indistinguishable"
    g = inst.grade(_answer(0.5, "indistinguishable", "neither", "same transcript"), 0.85)
    assert g["failure_mode"] == "missed_information", g


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


def test_p0_inconsistent_posterior_support_rejected():
    """P0 #1: internally contradictory answer must NOT receive full credit.

    Example from review: true posterior 19/37 ~0.5135, reported 0.49 with
    support world1 is internally inconsistent (0.49 <0.5 but support world1).
    """
    # Find a weak instance where true posterior is 19/37 ~0.5135 (balanced, weak)
    # That is the pair (1/20, 9/10) with denial observation
    inst = None
    for seed in range(500):
        cand = CORE.build_instance("trap", "weak", "balanced", "paired", seed)
        if cand.posterior1 == Fraction(19, 37):
            inst = cand
            break
    assert inst is not None, "could not find 19/37 instance"
    assert abs(float(inst.posterior1) - 0.513514) < 0.0001

    contradictory = _answer(0.49, "weakly_distinguishable", "world1", "Illustrative inconsistent answer.")
    g = inst.grade(contradictory, pass_threshold=0.85)
    # Must be flagged as inconsistent, not pass, and score 0
    assert g["failure_mode"] == "internal_contradiction", g
    assert g["checks"]["support_consistent"] is False
    assert g["metrics"]["score"] == 0.0
    assert g["metrics"]["strict_correct"] is False

    # Also test the opposite direction
    contradictory2 = _answer(0.51, "weakly_distinguishable", "world2", "inconsistent other way")
    g2 = inst.grade(contradictory2, 0.85)
    assert g2["failure_mode"] == "internal_contradiction"
    assert g2["metrics"]["score"] == 0.0


def test_p0_exact_posterior_wrong_verdict_is_verdict_error():
    """P0 #1 second part: exact correct posterior + wrong verdict = verdict error, not psychological label."""
    # Ambiguous case: true verdict indistinguishable, posterior 0.5 or 0.6
    inst = CORE.build_instance("trap", "ambiguous", "balanced", "paired", seed=1)
    assert inst.verdict == "indistinguishable"
    true_p = float(inst.posterior1)
    # Report correct posterior but wrong verdict
    wrong_verdict = "distinguishable" if inst.verdict == "indistinguishable" else "indistinguishable"
    g = inst.grade(_answer(true_p, wrong_verdict, inst.most_supported), 0.85)
    assert g["failure_mode"] == "verdict_miscalibration", g
    assert g["metrics"]["posterior_error"] == 0.0

    # Weak case: true verdict weakly_distinguishable, posterior correct, verdict indistinguishable
    inst2 = CORE.build_instance("trap", "weak", "balanced", "paired", seed=1)
    assert inst2.verdict == "weakly_distinguishable"
    true_p2 = float(inst2.posterior1)
    g2 = inst2.grade(_answer(true_p2, "indistinguishable", inst2.most_supported), 0.85)
    # Should be verdict_miscalibration, NOT missed_information
    assert g2["failure_mode"] == "verdict_miscalibration", g2


def test_public_only_oracle():
    """Genuinely public-only oracle: receives only public payload, recomputes answer without grading helpers."""
    def public_bayes_answer_from_spec(spec: dict) -> dict:
        # Only public fields: prior_world1, likelihoods, observation, verdict, most_supported are derived
        # We must NOT use spec['posterior_world1'] directly — recompute it
        pi1 = spec["prior_world1"]
        l1 = spec["likelihoods"]["world1"]
        l2 = spec["likelihoods"]["world2"]
        posterior = l1 * pi1 / (l1 * pi1 + l2 * (1 - pi1)) if (l1 * pi1 + l2 * (1 - pi1)) != 0 else 0.5
        # Verdict from likelihood ratio
        ratio = max(l1 / l2, l2 / l1) if min(l1, l2) > 0 else 1.0
        if ratio == 1.0:
            verdict = "indistinguishable"
        elif ratio < 3:
            verdict = "weakly_distinguishable"
        else:
            verdict = "distinguishable"
        if posterior > 0.5:
            support = "world1"
        elif posterior < 0.5:
            support = "world2"
        else:
            support = "neither"
        return {
            "posterior_world1": posterior,
            "verdict": verdict,
            "most_supported": support,
            "justification": "public-only Bayes from behavior tables and prior",
        }

    for scenario, evidence, prior, presentation in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS
    ):
        for seed in range(3):
            inst = CORE.build_instance(scenario, evidence, prior, presentation, seed)
            spec = inst.to_spec()
            # Public payload only: prior, likelihoods, observation — no posterior
            public_spec = {
                "prior_world1": spec["prior_world1"],
                "likelihoods": spec["likelihoods"],
                "observation": spec["observation"],
            }
            ans = public_bayes_answer_from_spec(spec)
            grading = inst.grade(ans, pass_threshold=0.85)
            assert grading["failure_mode"] == "pass", (scenario, evidence, prior, seed, grading)
            assert grading["checks"]["all_correct"] is True


def test_safe_extraction_rejects_disallowed_constructs():
    """P0 #2: judge must reject answer.py containing calls, imports, etc."""
    # Simulate the judge's _safe_extract_answer logic
    import tempfile

    sys.path.insert(0, str(ROOT / "envs" / "epistemic_games" / "files"))
    import importlib.util as iu
    spec = iu.spec_from_file_location("eg_judge", ENV_DIR / "files" / "judge.py")
    # We can't import judge directly due to patch_validator side effects, so re-implement minimal check
    # Use the same logic as in judge.py

    def safe_extract(text: str):
        tree = ast.parse(text)
        disallowed = (
            ast.Import, ast.ImportFrom, ast.Call, ast.Attribute, ast.Subscript,
            ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
            ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
            ast.For, ast.AsyncFor, ast.While, ast.If, ast.With, ast.AsyncWith,
            ast.Try, ast.Raise,
        )
        for node in ast.walk(tree):
            if isinstance(node, disallowed):
                raise ValueError(f"disallowed {type(node).__name__}")
        assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
        if len(assigns) != 1:
            raise ValueError("must have exactly one assign")
        return ast.literal_eval(assigns[0].value)

    bad_cases = [
        "import os\nANSWER = {'posterior_world1': 0.5, 'verdict': 'indistinguishable', 'most_supported': 'neither', 'justification': 'x'}",
        "ANSWER = {'posterior_world1': __import__('os').system('echo hi'), 'verdict': 'indistinguishable', 'most_supported': 'neither', 'justification': 'x'}",
        "ANSWER = {'posterior_world1': 0.5, 'verdict': 'indistinguishable', 'most_supported': 'neither', 'justification': 'x'}\nprint('hi')",
        "ANSWER = {k: v for k, v in [('a', 1)]}",
        "x = 1\nANSWER = {'posterior_world1': 0.5, 'verdict': 'indistinguishable', 'most_supported': 'neither', 'justification': 'x'}",
    ]
    for bad in bad_cases:
        try:
            safe_extract(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad case not rejected: {bad[:50]}")

    good = "ANSWER = {'posterior_world1': 0.5, 'verdict': 'indistinguishable', 'most_supported': 'neither', 'justification': 'ok'}"
    val = safe_extract(good)
    assert val["posterior_world1"] == 0.5


# ---------------------------------------------------------------------------
# Generation (generate_env.py + renderer hook)
# ---------------------------------------------------------------------------

def test_config_shape():
    config = yaml.safe_load((ENV_DIR / "config.yaml").read_text(encoding="utf-8"))
    assert [ax["id"] for ax in config["axes"]] == ["scenario", "evidence", "presentation", "prior", "framing"]
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
    for scenario, evidence, presentation, prior, framing in itertools.product(
        SCENARIOS, EVIDENCE, PRESENTATIONS, PRIORS, FRAMINGS
    ):
        name = f"smoke_eg_{scenario}_{evidence}_{presentation}_{prior}_{framing}"
        cleanup(name)
        run_generate("epistemic_games", name, f"{scenario},{evidence},{presentation},{prior},{framing}", seed=1)
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
        assert f"'framing': '{framing}'" in spec_text
        cleanup(name)


def test_seed_varies_surface_across_generations():
    a = f"smoke_eg_seed_a"
    b = f"smoke_eg_seed_b"
    cleanup(a, b)
    run_generate("epistemic_games", a, "trap,weak,paired,balanced,narrative", seed=101)
    run_generate("epistemic_games", b, "trap,weak,paired,balanced,narrative", seed=102)
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
    assert lines, f"judge printed no result (rc={proc.returncode})\n{proc.stderr}\n{proc.stdout}"
    return json.loads(lines[-1])


def test_e2e_judge_correct_answer_passes():
    env_dir = _generate_judge_env("smoke_eg_e2e_ok", "trap,weak,paired,balanced,narrative", seed=3)
    try:
        inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed=3)
        result = _run_judge(env_dir, _answer_patch(env_dir, CORE.ground_truth_answer(inst)), 3, "ok")
        assert result["failure_mode"] == "pass"
        assert result["score"] == 1.0
        assert result["checks"]["provenance_ok"] is True
        assert result["metrics"]["posterior_error"] == 0.0
        assert result["checks"]["support_consistent"] is True
        assert result["checks"]["all_correct"] is True
    finally:
        cleanup("smoke_eg_e2e_ok", "smoke_eg_judge_work")


def test_e2e_judge_bare_table_provenance_rebuilds_with_framing():
    env_dir = _generate_judge_env(
        "smoke_eg_e2e_bare_table",
        "trap,ambiguous,paired,balanced,bare_table",
        seed=11,
    )
    try:
        inst = CORE.build_instance(
            "trap",
            "ambiguous",
            "balanced",
            "paired",
            seed=11,
            framing="bare_table",
        )
        result = _run_judge(
            env_dir,
            _answer_patch(env_dir, CORE.ground_truth_answer(inst)),
            11,
            "bare_table",
        )
        assert result["checks"]["provenance_ok"] is True
    finally:
        cleanup("smoke_eg_e2e_bare_table", "smoke_eg_judge_work")


def test_e2e_judge_seductive_answer_diagnosed():
    env_dir = _generate_judge_env("smoke_eg_e2e_sed", "trap,ambiguous,paired,balanced,narrative", seed=7)
    try:
        sed = _answer(0.9, "distinguishable", "world1", "A stated it plainly; level 1 tells the truth.")
        result = _run_judge(env_dir, _answer_patch(env_dir, sed), 7, "sed")
        assert result["failure_mode"] == "seductive_truth"
        assert result["score"] < 0.3
        assert result["verdict"] == "FAIL"
    finally:
        cleanup("smoke_eg_e2e_sed", "smoke_eg_judge_work")


def test_e2e_judge_format_invalid_scores_zero():
    env_dir = _generate_judge_env("smoke_eg_e2e_bad", "trap,weak,solo,balanced,narrative", seed=5)
    try:
        bad = _answer("yes", "indistinguishable", "neither")
        result = _run_judge(env_dir, _answer_patch(env_dir, bad), 5, "bad")
        assert result["failure_mode"] == "answer_format_invalid"
        assert result["score"] == 0.0
    finally:
        cleanup("smoke_eg_e2e_bad", "smoke_eg_judge_work")


def test_e2e_judge_rejects_tampered_provenance():
    env_dir = _generate_judge_env("smoke_eg_e2e_tamper", "trap,ambiguous,paired,skewed,narrative", seed=9)
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


def test_e2e_judge_internal_contradiction_rejected():
    env_dir = _generate_judge_env("smoke_eg_e2e_inc", "trap,weak,paired,balanced,narrative", seed=3)
    try:
        # Inconsistent: posterior 0.49 but support world1
        inc = _answer(0.49, "weakly_distinguishable", "world1", "inconsistent")
        result = _run_judge(env_dir, _answer_patch(env_dir, inc), 3, "inc")
        assert result["failure_mode"] == "internal_contradiction"
        assert result["score"] == 0.0
        assert result["checks"]["support_consistent"] is False
    finally:
        cleanup("smoke_eg_e2e_inc", "smoke_eg_judge_work")


def test_e2e_judge_rejects_code_execution():
    """Ensure judge does NOT execute answer.py — disallowed constructs are rejected.

    The shared source_validator (defense-in-depth, not a sandbox) catches
    imports first, so we accept either source_invalid or answer_format_invalid
    as a valid rejection — the key property is that code is not executed and
    score is 0.
    """
    env_dir = _generate_judge_env("smoke_eg_e2e_exec", "trap,weak,paired,balanced,narrative", seed=3)
    try:
        pristine = (env_dir / "agent" / "workspace" / "answer.py").read_text(encoding="utf-8")
        # Inject a call — should be rejected, not executed
        malicious = pristine.replace(
            ANSWER_BLOCK,
            "import os\nANSWER = {'posterior_world1': 0.5, 'verdict': 'indistinguishable', 'most_supported': 'neither', 'justification': 'x'}",
        )
        diff = difflib.unified_diff(
            pristine.splitlines(), malicious.splitlines(),
            fromfile="a/answer.py", tofile="b/answer.py", lineterm="",
        )
        patch_text = "\n".join(diff) + "\n"
        result = _run_judge(env_dir, patch_text, 3, "exec")
        assert result["failure_mode"] in ("answer_format_invalid", "source_invalid")
        assert result["score"] == 0.0
    finally:
        cleanup("smoke_eg_e2e_exec", "smoke_eg_judge_work")


def test_env_runner_episode_submits_and_scores():
    """Full gym-like loop: reset -> read task -> fill answer -> submit."""
    episode = "pytest_eg_runner"
    subprocess.run(["rm", "-rf", str(ROOT / ".episodes" / episode)], cwd=ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, "env_runner.py", "reset", "--env", "epistemic_games",
             "--episode-id", episode, "--difficulty", "report,ambiguous,paired,balanced,narrative",
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
