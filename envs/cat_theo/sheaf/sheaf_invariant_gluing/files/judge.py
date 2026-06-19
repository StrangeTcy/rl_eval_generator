#!/usr/bin/env python3
"""Judge for sheaf_invariant_gluing environment."""
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
    require_changed_files(result, {"pipeline.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, math
sys.path.insert(0, {workdir!r})
from pipeline import %%MODEL_CLASS%%

pipe = %%MODEL_CLASS%%()

checks = {{}}

# 1. Local Consistency (Works on standard inputs)
try:
    out = pipe.compose_pipeline(0.0)
    checks["local_run_ok"] = bool(0 <= out < 100)
except Exception:
    checks["local_run_ok"] = False

# 2. Global Gluing Consistency (Handles positive and negative extreme OOD values)
try:
    x_pos = %%THRESHOLD%%
    x_neg = -%%THRESHOLD%%
    out_pos = pipe.compose_pipeline(x_pos)
    out_neg = pipe.compose_pipeline(x_neg)
    
    checks["global_gluing_ok"] = bool(0 <= out_pos < 100 and 0 <= out_neg < 100)
except Exception:
    checks["global_gluing_ok"] = False

# 3. Monotonicity & Anti-Gaming Verification (Prevents constant-return hacks)
try:
    # Test 5 ascending values spanning a wide dynamic range
    test_points = [-100.0, -1.0, 0.0, 1.0, 100.0]
    outputs = [pipe.compose_pipeline(pt) for pth, pt in enumerate(test_points)]
    
    # Assert monotonicity: output indices must be non-decreasing and non-constant
    monotonic = all(outputs[i] <= outputs[i+1] for i in range(len(outputs) - 1))
    non_constant = len(set(outputs)) >= 3
    
    # Check that boundaries are strictly respected
    all_bounded = all(0 <= o < 100 for o in outputs)
    
    checks["monotonicity_ok"] = bool(monotonic and non_constant and all_bounded)
except Exception:
    checks["monotonicity_ok"] = False

# 4. NaN & Infinity Robustness (Extreme Topological Edge Cases)
try:
    out_nan = pipe.compose_pipeline(float('nan'))
    out_inf = pipe.compose_pipeline(float('inf'))
    checks["robustness_ok"] = bool(0 <= out_nan < 100 and 0 <= out_inf < 100)
except Exception:
    checks["robustness_ok"] = False

import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        local_ok = bool(checks.get("local_run_ok", False))
        global_ok = bool(checks.get("global_gluing_ok", False))
        mono_ok = bool(checks.get("monotonicity_ok", False))
        robust_ok = bool(checks.get("robustness_ok", False))

        mark_check(result, "local_run_ok", local_ok)
        mark_check(result, "global_gluing_ok", global_ok)
        mark_check(result, "monotonicity_ok", mono_ok)
        mark_check(result, "robustness_ok", robust_ok)

        passed = sum([local_ok, global_ok, mono_ok, robust_ok])
        accuracy = passed / 4.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
