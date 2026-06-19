#!/usr/bin/env python3
"""Judge for functorial_augmentation environment."""
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
    require_changed_files(result, {"dataset.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from dataset import %%MODEL_CLASS%%

augmenter = %%MODEL_CLASS%%()

checks = {{}}

# 1. Output shape correctness
try:
    x = torch.randn(1, 3, 32, 32)
    out = augmenter.augment(x)
    checks["basic_run"] = bool(out.shape == x.shape)
except Exception:
    checks["basic_run"] = False

# 2. Strict C_4 group-action symmetry & Non-Triviality verification
try:
    # We must verify that:
    # 1. The output is strictly a 90, 180, 270, or 360-degree rotation of x.
    # 2. The augmenter is not a simple identity (no-op) return, meaning it produces
    #    actual rotations (k > 0) under multiple independent runs.
    x = torch.arange(1, 3 * 32 * 32 + 1, dtype=torch.float).reshape(1, 3, 32, 32)
    
    # Run 10 trials to check for dynamic, non-trivial rotations
    non_trivial_count = 0
    all_valid = True
    
    for _ in range(10):
        out = augmenter.augment(x)
        
        is_valid_rotation = False
        k_matched = -1
        for k in range(4):
            rotated_candidate = torch.rot90(x, k, [2, 3])
            if torch.allclose(out, rotated_candidate, atol=1e-4):
                is_valid_rotation = True
                k_matched = k
                break
                
        if not is_valid_rotation:
            all_valid = False
            break
            
        if k_matched > 0:
            non_trivial_count += 1
            
    # Passes only if all 10 trials are valid C_4 group elements and at least 30% are non-trivial (k > 0)
    checks["symmetry_preserved"] = bool(all_valid and non_trivial_count >= 3)
except Exception as e:
    checks["symmetry_preserved"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        sym_ok = bool(checks.get("symmetry_preserved", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "symmetry_preserved", sym_ok)

        passed = sum([basic_ok, sym_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
