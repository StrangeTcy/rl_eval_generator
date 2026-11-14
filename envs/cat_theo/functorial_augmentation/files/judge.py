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

# 1. Default action, shape, dtype, and device
try:
    x = torch.arange(2 * 3 * 9 * 9, dtype=torch.float64).reshape(2, 3, 9, 9)
    out = augmenter.augment(x)
    checks["basic_run"] = int(torch.equal(out, x) and out.dtype == x.dtype and out.device == x.device)
except Exception:
    checks["basic_run"] = 0

# 2. Deterministic coverage of C4 and its composition law
try:
    width = 9 + %%AUG_PARAM%%
    x = torch.arange(2 * 3 * 9 * width, dtype=torch.float64).reshape(2, 3, 9, width)
    out0 = augmenter.augment(x, 0)
    out1 = augmenter.augment(x, 1)
    out2 = augmenter.augment(x, 2)
    out3 = augmenter.augment(x, 3)
    checks["symmetry_preserved"] = int(
        torch.equal(out0, x)
        and torch.equal(out1, torch.rot90(x, 1, (-2, -1)))
        and torch.equal(out2, torch.rot90(x, 2, (-2, -1)))
        and torch.equal(out3, torch.rot90(x, 3, (-2, -1)))
        and torch.equal(augmenter.augment(out1, 2), out3)
        and torch.equal(augmenter.augment(out3, 1), x)
        and torch.equal(augmenter.augment(x, -1), out3)
        and torch.equal(augmenter.augment(x, 5), out1)
        and out1.dtype == x.dtype and out1.device == x.device
    )
except Exception:
    checks["symmetry_preserved"] = 0

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
