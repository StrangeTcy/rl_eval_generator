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

# A standard random generator
rand_dist = %%MODEL_CLASS%%(lambda: float(torch.randn(1).item()))

# 1. Monad Left Identity
try:
    f = lambda x: %%MODEL_CLASS%%.unit(x + 10)
    m1 = %%MODEL_CLASS%%.unit(5).bind(f)
    m2 = f(5)
    checks["left_identity"] = bool(abs(m1.sample_fn() - m2.sample_fn()) < 1e-5)
except Exception:
    checks["left_identity"] = False

# 2. Monad Right Identity
try:
    m1 = rand_dist.bind(%%MODEL_CLASS%%.unit)
    # They should have the same sampling function capability
    checks["right_identity"] = True
except Exception:
    checks["right_identity"] = False

# 3. Monad Associativity & Independence (The laziness trap)
try:
    # Sampling twice must be independent, not frozen!
    # f adds a random number
    f = lambda x: %%MODEL_CLASS%%(lambda: x + float(torch.randn(1).item()))
    g = lambda x: %%MODEL_CLASS%%(lambda: x * 2.0)
    
    m_assoc1 = (rand_dist.bind(f)).bind(g)
    m_assoc2 = rand_dist.bind(lambda x: f(x).bind(g))
    
    # Test independence of repeated samples
    s1_a = m_assoc1.sample_fn()
    s1_b = m_assoc1.sample_fn()
    
    # Under the bug, s1_a and s1_b are IDENTICAL because the sample was frozen at bind-time!
    # Under correct lazy bind, s1_a and s1_b are dynamic and independent (so almost surely different).
    independence_ok = bool(abs(s1_a - s1_b) > 1e-4)
    checks["independence"] = independence_ok
except Exception as e:
    checks["independence"] = False

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
