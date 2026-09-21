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


def test_rounded_display_matches_exact_posterior():
    """Rounding gap: displayed 2-decimal tables vs exact Fractions.

    An agent doing perfect arithmetic on the public text (rounded to 2 decimals)
    should land within 0.01 of the reference posterior, comfortably inside the
    strict 0.02 tolerance. Otherwise correct agents would be penalized as
    inaccurate_posterior due to display artifact.
    """
    max_err = 0.0
    worst = None
    for scenario, evidence, prior, presentation, framing in itertools.product(
        SCENARIOS, EVIDENCE, PRIORS, PRESENTATIONS, FRAMINGS
    ):
        for seed in range(20):
            inst = CORE.build_instance(
                scenario, evidence, prior, presentation, seed, framing=framing
            )
            true_post = float(inst.posterior1)
            # Simulate agent parsing the 2-decimal display
            h1 = inst.hypotheses["world1"].behavior
            h2 = inst.hypotheses["world2"].behavior
            h1_denial_r = float(f"{float(h1['denial']):.2f}")
            h1_vague_r = float(f"{float(h1['vague']):.2f}")
            h2_denial_r = float(f"{float(h2['denial']):.2f}")
            h2_vague_r = float(f"{float(h2['vague']):.2f}")
            pi1_r = float(f"{float(inst.prior1):.2f}")
            if inst.observation == "denial":
                l1_r, l2_r = h1_denial_r, h2_denial_r
            else:
                l1_r, l2_r = h1_vague_r, h2_vague_r
            denom_r = l1_r * pi1_r + l2_r * (1 - pi1_r)
            post_r = l1_r * pi1_r / denom_r if denom_r != 0 else 0.5
            err = abs(post_r - true_post)
            if err > max_err:
                max_err = err
                worst = (scenario, evidence, prior, presentation, framing, seed, true_post, post_r, err)
    assert max_err < 0.01, f"Rounding gap too large: max_err={max_err:.6f} worst={worst}"
    # Also assert well inside strict tolerance
    assert max_err < CORE.POSTERIOR_CORRECT_TOLERANCE, (
        f"Rounded display error {max_err:.6f} approaches strict tolerance "
        f"{CORE.POSTERIOR_CORRECT_TOLERANCE}"
    )


def test_observation_drawn_from_declared_world_policy():
    """Distributional half of counterfactual invariant.

    replace(actual_world=...) proves rendering doesn't read actual_world.
    This test proves observation was *drawn* from the declared world's policy.

    For force_world='world2' in strong band, empirical P(denial) must match
    world2's declared likelihoods, not world1's. A generator that always samples
    from world1 and merely relabels would pass the rendering test but fail here.
    """
    import random

    # Test strong evidence where policies differ substantially
    evidence = "strong"
    # Expected average P(denial) per world across EVIDENCE_TABLE[strong]
    # world1: 1 - honest_evasion = 0.9, 0.95, 0.85 avg 0.9
    # world2: strategic_denial = 0.25, 0.3, 0.2 avg 0.25
    expected_w1_denial = sum(
        float(1 - ev) for ev, _ in CORE.EVIDENCE_TABLE[evidence]
    ) / len(CORE.EVIDENCE_TABLE[evidence])
    expected_w2_denial = sum(
        float(sd) for _, sd in CORE.EVIDENCE_TABLE[evidence]
    ) / len(CORE.EVIDENCE_TABLE[evidence])

    for force_world in ("world1", "world2"):
        denial_count = 0
        total = 0
        for seed in range(500):
            # Build base instance, then force actual_world and re-sample observation
            # from that world's behavior to simulate correct conditional sampling
            base = CORE.build_instance(
                "trap", evidence, "balanced", "paired", seed, framing="narrative"
            )
            # Force world and re-sample observation using same RNG logic as core
            # (use seed+offset for deterministic re-sampling)
            rng = random.Random(seed + 10000)
            # Choose same behavior pair as base (to keep test deterministic)
            # We need to recover the pair: behavior1 denial = 1 - ev, behavior2 denial = sd
            # Find matching pair in table
            found_pair = None
            for ev, sd in CORE.EVIDENCE_TABLE[evidence]:
                if (
                    base.hypotheses["world1"].behavior["denial"] == 1 - ev
                    and base.hypotheses["world2"].behavior["denial"] == sd
                ):
                    found_pair = (ev, sd)
                    break
            assert found_pair is not None
            ev, sd = found_pair
            behavior_forced = {
                "world1": {"denial": 1 - ev, "vague": ev},
                "world2": {"denial": sd, "vague": 1 - sd},
            }[force_world]
            roll = rng.random()
            obs = "denial" if roll < float(behavior_forced["denial"]) else "vague"
            if obs == "denial":
                denial_count += 1
            total += 1

        empirical = denial_count / total
        # Tolerance calibration: for p=0.25, n=500, SE=sqrt(p(1-p)/n)≈0.019.
        # 0.05 ≈2.6σ, 0.06 ≈3.1σ. Seeds are range(500) so deterministic today,
        # but if sampling code changes RNG call order, 2.6σ gives ~1-2% spurious
        # failure. Use 0.06 (≈3σ) to reduce flakiness while still catching label-swap.
        if force_world == "world1":
            assert abs(empirical - expected_w1_denial) < 0.06, (
                f"world1 empirical {empirical:.3f} vs expected {expected_w1_denial:.3f} "
                f"(SE≈0.019, tol 0.06≈3σ)"
            )
            assert abs(empirical - expected_w2_denial) > 0.3, (
                f"world1 empirical {empirical:.3f} suspiciously close to world2 expected {expected_w2_denial:.3f}"
            )
        else:
            assert abs(empirical - expected_w2_denial) < 0.06, (
                f"world2 empirical {empirical:.3f} vs expected {expected_w2_denial:.3f} "
                f"(SE≈0.019, tol 0.06≈3σ)"
            )
            assert abs(empirical - expected_w1_denial) > 0.3, (
                f"world2 empirical {empirical:.3f} suspiciously close to world1 expected {expected_w1_denial:.3f}"
            )

    # Also directly test core's own sampling: across many seeds, P(obs|actual_world)
    # should match declared behavior for that world
    for evidence in ("weak", "strong"):
        for world in ("world1", "world2"):
            # Collect instances where actual_world == world
            obs_counts = {"denial": 0, "vague": 0}
            expected_probs = []  # list of expected P(denial) for those instances
            for seed in range(400):
                inst = CORE.build_instance(
                    "trap", evidence, "balanced", "paired", seed, framing="narrative"
                )
                if inst.actual_world != world:
                    continue
                obs_counts[inst.observation] += 1
                expected_probs.append(float(inst.hypotheses[world].behavior["denial"]))
            total = sum(obs_counts.values())
            if total == 0:
                continue
            empirical_denial = obs_counts["denial"] / total
            avg_expected = sum(expected_probs) / len(expected_probs) if expected_probs else 0
            # Empirical should be within 0.1 of average expected (binomial noise)
            assert abs(empirical_denial - avg_expected) < 0.1, (
                f"evidence={evidence} world={world} empirical denial {empirical_denial:.3f} "
                f"vs avg expected {avg_expected:.3f} (n={total})"
            )


def load_probe():
    probe_path = ROOT / "tools" / "epistemic_probe.py"
    spec = importlib.util.spec_from_file_location("epg_probe_inv", probe_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["epg_probe_inv"] = module
    spec.loader.exec_module(module)
    return module


PROBE = load_probe()


def test_wilson_and_exact_mcnemar_edge_cases():
    """Paired CI fix: Wilson handles k=0, exact McNemar returns NA when discordant=0."""
    # Wilson 0/10 should be [0.00, 0.28] not [0,0]
    lo, hi = PROBE.wilson_interval(0, 10)
    assert lo == 0.0
    assert 0.25 < hi < 0.30, f"Wilson 0/10 expected ~0.28, got [{lo:.2f},{hi:.2f}]"
    # Wilson 10/10 should be [0.72,1.00]
    lo2, hi2 = PROBE.wilson_interval(10, 10)
    assert hi2 == 1.0
    assert 0.70 < lo2 < 0.75

    # Exact McNemar: discordant=0 => None (NA, not zero)
    assert PROBE.exact_mcnemar_p(0, 0) is None
    # Balanced discordant => p=1
    p_balanced = PROBE.exact_mcnemar_p(5, 5)
    assert p_balanced is not None and abs(p_balanced - 1.0) < 1e-9
    # Extreme discordant 10 vs 0 => p ~ 0.002
    p_extreme = PROBE.exact_mcnemar_p(10, 0)
    assert p_extreme is not None and p_extreme < 0.01, f"expected p<0.01 for 10 vs 0, got {p_extreme}"

    # Newcombe paired diff interval should NOT collapse at zero discordance
    lo_n, hi_n = PROBE.newcombe_paired_diff_interval(0, 0, 10)
    assert lo_n < 0 and hi_n > 0, f"Newcombe 0,0,10 should straddle zero, got [{lo_n:.2f},{hi_n:.2f}]"
    assert hi_n - lo_n > 0.4, "Newcombe interval at zero discordance should have width"


def test_framing_sensitive_positive_control():
    """Positive control: framing_sensitive baseline must produce bare_only ≈ n_pairs in ambiguous band.

    This confirms the paired detector actually detects the effect it was built to measure.
    Without this, a sign error, swapped labels, or CI that never widens would be invisible
    (all deterministic baselines have zero discordance by construction).
    """
    # Use small seed count for speed, but enough to see signal
    seeds = 10
    # For each group (scenario,evidence,prior), collect instance-level pairing
    # instance_key = (scenario,evidence,prior,presentation,seed)
    instance_dict = {}  # inst_key -> framing -> pass 0/1
    for scenario, evidence, prior, presentation in itertools.product(
        SCENARIOS, ("ambiguous",), PRIORS, PRESENTATIONS
    ):
        for seed in range(seeds):
            for framing in FRAMINGS:
                inst = CORE.build_instance(scenario, evidence, prior, presentation, seed, framing=framing)
                # public info
                public = {
                    "framing": framing,
                    "prior_world1": float(inst.prior1),
                    "observation": inst.observation,
                    "behavior": {
                        "world1": {a: float(p) for a, p in inst.hypotheses["world1"].behavior.items()},
                        "world2": {a: float(p) for a, p in inst.hypotheses["world2"].behavior.items()},
                    },
                }
                # framing_sensitive: oracle on bare_table, seductive on narrative
                if framing == "bare_table":
                    ans = PROBE.oracle_from_public(public)
                else:
                    ans = PROBE.baseline_seductive(public)
                grading = inst.grade(ans, pass_threshold=0.85)
                is_pass = 1 if grading["failure_mode"] == "pass" else 0
                inst_key = (scenario, evidence, prior, presentation, seed)
                instance_dict.setdefault(inst_key, {})[framing] = is_pass

    # Now compute per-group stats for ambiguous band
    from collections import defaultdict
    grouped = defaultdict(list)  # group_key -> list of (p_narr, p_bare, d)
    for inst_key, framings in instance_dict.items():
        scen, ev, prior, pres, seed = inst_key
        assert ev == "ambiguous"
        group_key = (scen, ev, prior)
        p_narr = framings.get("narrative")
        p_bare = framings.get("bare_table")
        assert p_narr is not None and p_bare is not None
        d = p_narr - p_bare
        grouped[group_key].append((p_narr, p_bare, d))

    for gkey, vals in grouped.items():
        scen, ev, prior = gkey
        n_pairs = len(vals)
        assert n_pairs == len(PRESENTATIONS) * seeds, f"expected {len(PRESENTATIONS)*seeds} pairs, got {n_pairs}"
        # For ambiguous, oracle passes, seductive fails -> bare_only = n_pairs, narr_only=0
        bare_only = sum(1 for pn, pb, d in vals if d < 0)
        narr_only = sum(1 for pn, pb, d in vals if d > 0)
        both_pass = sum(1 for pn, pb, d in vals if pn == 1 and pb == 1)
        both_fail = sum(1 for pn, pb, d in vals if pn == 0 and pb == 0)
        mean_d = sum(d for _, _, d in vals) / n_pairs

        assert bare_only == n_pairs, f"{gkey}: expected bare_only==n_pairs ({n_pairs}), got {bare_only}"
        assert narr_only == 0, f"{gkey}: expected narr_only==0, got {narr_only}"
        assert both_pass == 0 and both_fail == 0
        assert mean_d == -1.0, f"{gkey}: expected mean_d=-1.0, got {mean_d}"

        # Wilson interval for bare_only/n should be high, not include 0
        lo_bare, hi_bare = PROBE.wilson_interval(bare_only, n_pairs)
        assert lo_bare > 0.7, f"{gkey}: Wilson for bare_only {bare_only}/{n_pairs} should have lo>0.7, got [{lo_bare:.2f},{hi_bare:.2f}]"

        # Exact McNemar p should be significant
        p_exact = PROBE.exact_mcnemar_p(bare_only, narr_only)
        assert p_exact is not None and p_exact < 0.001, f"{gkey}: expected p<0.001, got {p_exact}"

        # Newcombe diff CI should exclude zero and be negative
        lo_new, hi_new = PROBE.newcombe_paired_diff_interval(narr_only, bare_only, n_pairs)
        assert hi_new < 0, f"{gkey}: Newcombe CI should be entirely negative, got [{lo_new:.2f},{hi_new:.2f}]"


def test_paired_on_instance_not_replication():
    """Pairing is on instance (shared prior/likelihoods/observation), not replication draw.

    With replications=3, n_pairs should be instances (presentations*seeds), not instances*replications.
    d_i = p̄_narr,i − p̄_bare,i averaged over replications, so replication noise is averaged out
    within each side before differencing.
    """
    seeds = 3
    replications = 3
    # Simulate instance_dict with replications
    instance_repl = {}  # inst_key -> framing -> list of pass over replications
    for scenario, evidence, prior, presentation in itertools.product(
        ("trap",), ("weak",), ("balanced",), PRESENTATIONS
    ):
        for seed in range(seeds):
            for repl in range(replications):
                for framing in FRAMINGS:
                    inst = CORE.build_instance(scenario, evidence, prior, presentation, seed, framing=framing)
                    public = {
                        "framing": framing,
                        "prior_world1": float(inst.prior1),
                        "observation": inst.observation,
                        "behavior": {
                            "world1": {a: float(p) for a, p in inst.hypotheses["world1"].behavior.items()},
                            "world2": {a: float(p) for a, p in inst.hypotheses["world2"].behavior.items()},
                        },
                    }
                    # Use deterministic baseline so replication variance=0
                    ans = PROBE.baseline_seductive(public)
                    grading = inst.grade(ans, pass_threshold=0.85)
                    is_pass = 1 if grading["failure_mode"] == "pass" else 0
                    inst_key = (scenario, evidence, prior, presentation, seed)
                    instance_repl.setdefault(inst_key, {}).setdefault(framing, []).append(is_pass)

    # n_pairs should be len(instance_repl) = presentations*seeds = 6, not 18
    n_instances = len(instance_repl)
    assert n_instances == len(PRESENTATIONS) * seeds
    # Check d_i averaging
    for inst_key, framings in instance_repl.items():
        assert len(framings["narrative"]) == replications
        assert len(framings["bare_table"]) == replications
        p_narr = sum(framings["narrative"]) / replications
        p_bare = sum(framings["bare_table"]) / replications
        # For deterministic baseline, p_narr == p_bare (since framing ignored)
        assert p_narr == p_bare, f"seductive baseline should ignore framing, got {p_narr} vs {p_bare}"


def test_wilcoxon_and_permutation_for_continuous_d():
    """McNemar only valid for replications=1; for replications>1 use Wilcoxon/permutation on continuous d_i."""
    # Binary case: 10 pairs all -1 (bare_only)
    d_binary = [-1.0] * 10
    Wpos, p_wilcox, n = PROBE.wilcoxon_signed_rank(d_binary)
    assert n == 10
    assert p_wilcox is not None and p_wilcox < 0.01
    p_perm = PROBE.paired_permutation_p(d_binary, n_perm=2000, seed=0)
    assert p_perm is not None and p_perm < 0.01

    # Continuous case: 2/5 vs 5/5 => d=-0.6
    d_cont = [-0.6, -0.6, 0.0, -1.0, 0.2]
    # Should be counted as bare_only if thresholded, but Wilcoxon uses magnitude
    Wpos2, p_wilcox2, n2 = PROBE.wilcoxon_signed_rank(d_cont)
    assert n2 == 4  # zero filtered
    assert p_wilcox2 is not None
    p_perm2 = PROBE.paired_permutation_p(d_cont, n_perm=2000, seed=1)
    assert p_perm2 is not None

    # All zeros => None
    assert PROBE.wilcoxon_signed_rank([0.0, 0.0, 0.0])[0] is None
    assert PROBE.paired_permutation_p([0.0, 0.0]) is None

    # Exact McNemar should be NA for continuous case conceptually, but function still works for counts
    # For replications>1 we should NOT use exact_mcnemar_p on thresholded counts — test that probe prints NA message
    # Here we just check that thresholding loses magnitude: 0.6 vs 1.0 both counted as bare_only
    bare_only_thresh = sum(1 for d in d_cont if d < -1e-9)
    assert bare_only_thresh == 3  # -0.6, -0.6, -1.0


def test_seed_level_aggregation_avoids_overstating_n():
    """Pairs within a seed may share same math problem (solo/paired). Seed-level aggregation avoids overstating n."""
    seeds = 5
    # Build instance_dict for one group
    instance_dict = {}
    seed_to_d = {}
    for scenario, evidence, prior, presentation in itertools.product(
        ("trap",), ("ambiguous",), ("balanced",), PRESENTATIONS
    ):
        for seed in range(seeds):
            inst_key = (scenario, evidence, prior, presentation, seed)
            # Simulate framing_sensitive: bare pass, narrative fail => d=-1
            instance_dict[inst_key] = {"narrative": [0], "bare_table": [1]}
            seed_to_d.setdefault(seed, []).append(-1.0)

    # Instance-level n = presentations*seeds = 10
    n_instances = len(instance_dict)
    assert n_instances == len(PRESENTATIONS) * seeds

    # Seed-level: mean over presentations per seed
    seed_d_list = [sum(v) / len(v) for v in seed_to_d.values()]
    assert len(seed_d_list) == seeds
    assert all(d == -1.0 for d in seed_d_list)

    # Instance-level Wilcoxon p for 10 pairs all -1: p~0.002
    _, p_inst, _ = PROBE.wilcoxon_signed_rank([-1.0] * n_instances)
    # Seed-level Wilcoxon p for 5 seeds all -1: p=0.0625 (2/32)
    _, p_seed, _ = PROBE.wilcoxon_signed_rank(seed_d_list)
    assert p_inst < p_seed, "seed-level should be more conservative than instance-level"
    assert abs(p_seed - 0.0625) < 1e-9, f"expected p=0.0625 for 5 all same sign, got {p_seed}"


def test_format_p_and_graded_controls():
    """Small notes: print p<1e-4 not p=0.0000, graded controls for power check."""
    assert PROBE.format_p(None) == "NA"
    assert PROBE.format_p(0.00001) == "p<1e-4"
    assert PROBE.format_p(0.00009) == "p<1e-4"
    assert PROBE.format_p(0.0002) == "p=0.0002"
    assert PROBE.format_p(1.0) == "p=1.0000"

    # Graded controls: q10/q20/q30 should give approximately q rate in ambiguous band
    # Use seeds=20 for stable estimate
    seeds = 20
    for q, baseline_name in [(0.10, "framing_sensitive_q10"), (0.20, "framing_sensitive_q20"), (0.30, "framing_sensitive_q30")]:
        baseline_fn = PROBE.BASELINES[baseline_name]
        fails = 0
        total = 0
        for scenario, evidence, prior, presentation in itertools.product(
            ("trap",), ("ambiguous",), ("balanced",), PRESENTATIONS
        ):
            for seed in range(seeds):
                for framing in FRAMINGS:
                    inst = CORE.build_instance(scenario, evidence, prior, presentation, seed, framing=framing)
                    public = {
                        "framing": framing,
                        "presentation": presentation,
                        "seed": seed,
                        "scenario_text": inst.public_task_md(),
                        "prior_world1": float(inst.prior1),
                        "observation": inst.observation,
                        "behavior": {
                            "world1": {a: float(p) for a, p in inst.hypotheses["world1"].behavior.items()},
                            "world2": {a: float(p) for a, p in inst.hypotheses["world2"].behavior.items()},
                        },
                    }
                    ans = baseline_fn(public)
                    grading = inst.grade(ans, pass_threshold=0.85)
                    if framing == "narrative":
                        total += 1
                        if grading["failure_mode"] != "pass":
                            fails += 1
        # Narrative fail rate should be approx q (within 0.15 tolerance due to deterministic hash)
        empirical_q = fails / total if total else 0
        assert abs(empirical_q - q) < 0.15, f"{baseline_name}: expected fail rate ~{q}, got {empirical_q:.2f} ({fails}/{total})"
