#!/usr/bin/env python3
"""Judge for compositional_optimizer environment."""
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
    require_changed_files(result, {"optimizer.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from optimizer import MomentumStep

checks = {{}}

# 1. Output shape correctness
try:
    opt = MomentumStep()
    p = torch.randn(2, 2)
    g = torch.randn(2, 2)
    out = opt.update(p, g)
    checks["basic_run"] = bool(out.shape == p.shape)
except Exception:
    checks["basic_run"] = False

# 2. Strict State Isolation & Associativity Verification
try:
    # Compose two separate MomentumStep modules in the same chain
    opt1 = MomentumStep(beta=0.9)
    opt2 = MomentumStep(beta=0.99)
    
    p = torch.randn(2, 2)
    g = torch.randn(2, 2)
    
    # Run step 1
    v1 = opt1.update(p, g)
    v2 = opt2.update(p, v1)
    
    # Expected reference calculation (fully isolated):
    v1_ref = 0.1 * g
    v2_ref = 0.01 * v1_ref
    
    # If they collided via the class-level state, v2 and v2_ref will differ!
    checks["state_isolated"] = bool(torch.allclose(v2, v2_ref, atol=1e-5))
except Exception as e:
    checks["state_isolated"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        assoc_ok = bool(checks.get("state_isolated", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "state_isolated", assoc_ok)

        passed = sum([basic_ok, assoc_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
