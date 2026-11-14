#!/usr/bin/env python3
"""Judge for stochastic_monad environment."""
import os
import sys
import torch

from judge_lib import (base_result, emit, eval_env, judge_event, make_workdir,
                       mark_check, run, score_from_accuracy, scrub_workdir,
                       set_failure, set_metric, train_env, validate_submission,
                       require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%

def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"monad.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from monad import %%MODEL_CLASS%%

checks = {{}}

torch.manual_seed(%%JUDGE_SEED%%)
sigma = %%SIGMA_VAL%%
rand_dist = %%MODEL_CLASS%%(lambda: sigma * torch.randn(128, dtype=torch.float64))

# 1. Monad left identity
try:
    f = lambda x: %%MODEL_CLASS%%.unit(x + 10)
    m1 = %%MODEL_CLASS%%.unit(5).bind(f)
    m2 = f(5)
    checks["left_identity"] = int(abs(m1.sample_fn() - m2.sample_fn()) < 1e-5)
except Exception:
    checks["left_identity"] = 0

# 2. Right identity preserves deferred sampling and random-stream state
try:
    rng_before = torch.random.get_rng_state().clone()
    m1 = rand_dist.bind(%%MODEL_CLASS%%.unit)
    lazy_ok = int(torch.equal(rng_before, torch.random.get_rng_state()))
    torch.random.set_rng_state(rng_before)
    actual = m1.sample_fn()
    torch.random.set_rng_state(rng_before)
    expected = rand_dist.sample_fn()
    checks["right_identity"] = int(lazy_ok and torch.equal(actual, expected))
except Exception:
    checks["right_identity"] = 0

# 3. Associativity under a common random stream and fresh repeated samples
try:
    f = lambda x: %%MODEL_CLASS%%(lambda: x + sigma * torch.randn(128, dtype=torch.float64))
    g = lambda x: %%MODEL_CLASS%%(lambda: x * 2.0)
    rng_before = torch.random.get_rng_state().clone()
    left = rand_dist.bind(f).bind(g)
    right = rand_dist.bind(lambda x: f(x).bind(g))
    lazy_ok = int(torch.equal(rng_before, torch.random.get_rng_state()))
    torch.random.set_rng_state(rng_before)
    sample_left = left.sample_fn()
    torch.random.set_rng_state(rng_before)
    sample_right = right.sample_fn()
    repeated = right.sample_fn()
    checks["independence"] = int(
        lazy_ok and torch.equal(sample_left, sample_right)
        and not torch.equal(sample_right, repeated)
        and torch.std(sample_left).item() > sigma
    )
except Exception:
    checks["independence"] = 0

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        left_ok = bool(checks.get("left_identity", False))
        right_ok = bool(checks.get("right_identity", False))
        indep_ok = bool(checks.get("independence", False))

        mark_check(result, "left_identity", left_ok)
        mark_check(result, "right_identity", right_ok)
        mark_check(result, "independence", indep_ok)

        passed = sum([left_ok, right_ok, indep_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
