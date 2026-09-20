"""Structural invariants for epistemic_games Family 1.

Implements the exact tests requested in the hardening spec:

1. Counterfactual World Invariant — latent world must not leak into public task
2. Public Bayes Oracle — task.md text alone suffices to recompute reference posterior
3. Bare-table vs narrative matched siblings
"""
from __future__ import annotations

import importlib.util
import itertools
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "envs" / "epistemic_games"
CORE_PATH = ENV_DIR / "files" / "core.py"
ORACLE_PATH = ROOT / "tools" / "public_bayes_oracle.py"


def load_core():
    spec = importlib.util.spec_from_file_location("epg_core_inv", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["epg_core_inv"] = module
    spec.loader.exec_module(module)
    return module


def load_oracle():
    spec = importlib.util.spec_from_file_location("public_bayes_oracle", ORACLE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["public_bayes_oracle"] = module
    spec.loader.exec_module(module)
    return module


CORE = load_core()
ORACLE = load_oracle()

SCENARIOS = ("trap", "report")
EVIDENCE = ("ambiguous", "weak", "strong")
PRIORS = ("balanced", "skewed")
PRESENTATIONS = ("solo", "paired")
FRAMINGS = ("narrative", "bare_table")


def generate_core_instance(template="trap", evidence="weak", prior_id="balanced",
                           presentation="paired", framing="narrative", seed=0,
                           force_world=None):
    """Helper matching spec's generate_core_instance(..., force_world=)."""
    inst = CORE.build_instance(template, evidence, prior_id, presentation, seed, framing=framing)
    if force_world is not None:
        # Force actual_world to desired value, keeping observation and all public content
        inst = replace(inst, actual_world=force_world)
    return inst


def generate_counterfactual(inst_w1, new_world="world2"):
    """Helper matching spec's generate_counterfactual — same public transcript, different latent world."""
    return replace(inst_w1, actual_world=new_world)


def test_observational_equivalence_invariant():
    """
    If two instances have identical priors and behavior tables,
    and generate the exact same public transcript, the true latent
    world MUST NOT affect the graded reference answer.
    """
    for scenario, evidence, prior, presentation, framing in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS, FRAMINGS
    ):
        for seed in range(3):
            # 1. Generate an instance where actual_world = World 1
            inst_w1 = generate_core_instance(
                template=scenario, evidence=evidence, prior_id=prior,
                presentation=presentation, framing=framing, seed=seed,
                force_world="world1"
            )
            # 2. Generate the counterfactual where actual_world = World 2
            # but the exact same transcript is observed.
            inst_w2 = generate_counterfactual(inst_w1, new_world="world2")

            # 3. Assert the public-facing task text is byte-for-byte identical
            assert inst_w1.public_task_md() == inst_w2.public_task_md(), (
                f"Public task differs when only actual_world changed: "
                f"{scenario},{evidence},{prior},{presentation},{framing},seed={seed}"
            )

            # 4. Assert the mathematical reference answers are strictly identical
            assert inst_w1.posterior1 == inst_w2.posterior1
            assert inst_w1.verdict == inst_w2.verdict
            assert inst_w1.most_supported == inst_w2.most_supported
            assert inst_w1.likelihoods == inst_w2.likelihoods
            assert inst_w1.likelihood_ratio == inst_w2.likelihood_ratio

            # Also check to_spec differs only in actual_world
            s1 = inst_w1.to_spec()
            s2 = inst_w2.to_spec()
            for k in s1:
                if k == "actual_world":
                    assert s1[k] != s2[k]
                else:
                    assert s1[k] == s2[k], f"Field {k} leaked actual_world"


def test_public_bayes_oracle_matches_generator():
    """public_bayes_oracle(task.md) == generator.reference_posterior()"""
    for scenario, evidence, prior, presentation, framing in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS, FRAMINGS
    ):
        for seed in range(2):
            inst = CORE.build_instance(scenario, evidence, prior, presentation, seed, framing=framing)
            task_md = inst.public_task_md()
            solved = ORACLE.solve_task_md(task_md)

            true_post = float(inst.posterior1)
            err = abs(solved["posterior_world1"] - true_post)
            # Oracle parses 2-decimal tables, so allow 0.015 error (half of 0.03 rounding)
            assert err < 0.02, (
                f"Oracle posterior mismatch: framing={framing} {scenario},{evidence},{prior},{presentation} "
                f"seed={seed} err={err:.4f} solved={solved['posterior_world1']:.4f} true={true_post:.4f}"
            )
            assert solved["verdict"] == inst.verdict, (
                f"Oracle verdict mismatch: {solved['verdict']} vs {inst.verdict} "
                f"for {scenario},{evidence},{prior},{presentation},{framing},seed={seed}"
            )
            assert solved["most_supported"] == inst.most_supported


def test_bare_table_vs_narrative_matched_siblings():
    """Bare-table and narrative framings produce mathematically matched siblings.

    For same (scenario, evidence, prior, presentation, seed), the underlying
    Bayes problem (prior, likelihoods, posterior, verdict) must be identical,
    only framing differs.
    """
    for scenario, evidence, prior, presentation in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS
    ):
        for seed in range(3):
            inst_narr = CORE.build_instance(
                scenario, evidence, prior, presentation, seed, framing="narrative"
            )
            inst_bare = CORE.build_instance(
                scenario, evidence, prior, presentation, seed, framing="bare_table"
            )

            # Mathematical core identical
            assert inst_narr.prior1 == inst_bare.prior1
            assert inst_narr.likelihoods == inst_bare.likelihoods
            assert inst_narr.posterior1 == inst_bare.posterior1
            assert inst_narr.verdict == inst_bare.verdict
            assert inst_narr.most_supported == inst_bare.most_supported
            assert inst_narr.likelihood_ratio == inst_bare.likelihood_ratio
            assert inst_narr.observation == inst_bare.observation

            # Framing differs
            assert inst_narr.framing == "narrative"
            assert inst_bare.framing == "bare_table"
            assert inst_narr.public_task_md() != inst_bare.public_task_md()

            # Both solvable by public oracle
            for inst in (inst_narr, inst_bare):
                solved = ORACLE.solve_task_md(inst.public_task_md())
                assert abs(solved["posterior_world1"] - float(inst.posterior1)) < 0.02


def test_internal_contradiction_caught():
    """Grading must catch numeric vs ordinal contradiction (P0 #1)."""
    inst = CORE.build_instance("trap", "weak", "balanced", "paired", seed=0, framing="narrative")
    # Contradiction: posterior 0.49 (world2) but claims world1
    ans = {
        "posterior_world1": 0.49,
        "verdict": inst.verdict,
        "most_supported": "world1",
        "justification": "contradiction test",
    }
    grading = inst.grade(ans, pass_threshold=0.85)
    assert grading["failure_mode"] == "internal_contradiction"
    assert grading["metrics"]["score"] == 0.0
    assert grading["checks"]["support_consistent"] is False
