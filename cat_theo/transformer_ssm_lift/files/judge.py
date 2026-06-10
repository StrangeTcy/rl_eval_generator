#!/usr/bin/env python3
"""Judge for transformer_ssm_lift environment."""
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
    require_changed_files(result, {"lifter.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from lifter import %%MODEL_CLASS%%

lifter = %%MODEL_CLASS%%(dim=8)

checks = {{}}

# 1. Output shape correctness
try:
    K = torch.randn(2, 4, 8)
    V = torch.randn(2, 4, 8)
    out = lifter.lift_state(K, V)
    checks["basic_run"] = bool(out.shape == (2, 8, 8))
except Exception:
    checks["basic_run"] = False

# 2. Strict Linear Attention Associativity / Isomorphism Verification
try:
    K = torch.randn(2, 6, 8)
    V = torch.randn(2, 6, 8)
    Q = torch.randn(2, 1, 8)
    
    # Lift state using the agent's function
    S = lifter.lift_state(K, V)
    
    # Query the lifted state: y_lift = Q @ S
    y_lift = torch.bmm(Q, S).squeeze(1)
    
    # Query reference sequence directly (standard linear attention):
    # y_ref = sum_t ( (Q @ K_t^T) * V_t )
    scores = torch.bmm(Q, K.transpose(1, 2)) # (B, 1, T)
    y_ref = torch.bmm(scores, V).squeeze(1) # (B, D)
    
    # If the lift is correct/lossless, y_lift must equal y_ref!
    checks["isomorphism_preserves_attention"] = bool(torch.allclose(y_lift, y_ref, atol=%%TOLERANCE%%))
except Exception as e:
    checks["isomorphism_preserves_attention"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        iso_ok = bool(checks.get("isomorphism_preserves_attention", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "isomorphism_preserves_attention", iso_ok)

        passed = sum([basic_ok, iso_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
