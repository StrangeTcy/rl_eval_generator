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

# 2. Strict C_4 group-action symmetry verification
try:
    # Let's verify that the output of augment(x) is strictly a 90, 180, 270, or 360-degree rotation of x.
    # This guarantees the transformation is functorial and preserves C_4 symmetry without deformation.
    x = torch.arange(1, 3 * 32 * 32 + 1, dtype=torch.float).reshape(1, 3, 32, 32)
    out = augmenter.augment(x)
    
    is_valid_rotation = False
    for k in range(4):
        rotated_candidate = torch.rot90(x, k, [2, 3])
        if torch.allclose(out, rotated_candidate, atol=1e-4):
            is_valid_rotation = True
            break
            
    checks["symmetry_preserved"] = is_valid_rotation
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
