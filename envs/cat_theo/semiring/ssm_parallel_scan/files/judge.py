#!/usr/bin/env python3
"""Judge for ssm_parallel_scan environment."""
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
    require_changed_files(result, {"ssm.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from ssm import %%MODEL_CLASS%%

scanner = %%MODEL_CLASS%%()

checks = {{}}

# 1. Output shape correctness & Semantic Correctness (Not a trivial associative hack!)
try:
    u1 = torch.randn(4, 8)
    M1 = torch.randn(4, 8)
    u2 = torch.randn(4, 8)
    M2 = torch.randn(4, 8)
    
    u_out, M_out = scanner.combine((u1, M1), (u2, M2))
    
    # Expected sequential recurrent combination (M2 * u1 + u2, M2 * M1)
    expected_u = M2 * u1 + u2
    expected_M = M2 * M1
    
    checks["basic_run"] = bool(
        u_out.shape == u1.shape and 
        M_out.shape == M1.shape and 
        torch.allclose(u_out, expected_u, atol=1e-4) and 
        torch.allclose(M_out, expected_M, atol=1e-4)
    )
except Exception:
    checks["basic_run"] = False

# 2. Strict Monoid Associativity Verification
try:
    s1 = (torch.randn(4, 8), torch.randn(4, 8))
    s2 = (torch.randn(4, 8), torch.randn(4, 8))
    s3 = (torch.randn(4, 8), torch.randn(4, 8))
    
    # Path A: (s1 o s2) o s3
    left = scanner.combine(scanner.combine(s1, s2), s3)
    
    # Path B: s1 o (s2 o s3)
    right = scanner.combine(s1, scanner.combine(s2, s3))
    
    # Assert associativity commutes perfectly
    u_ok = bool(torch.allclose(left[0], right[0], atol=%%TOLERANCE%%))
    M_ok = bool(torch.allclose(left[1], right[1], atol=%%TOLERANCE%%))
    
    checks["associativity_commutes"] = bool(u_ok and M_ok)
except Exception as e:
    checks["associativity_commutes"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        assoc_ok = bool(checks.get("associativity_commutes", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "associativity_commutes", assoc_ok)

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
