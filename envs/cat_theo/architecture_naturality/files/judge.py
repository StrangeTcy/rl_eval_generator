#!/usr/bin/env encoding="utf-8"
"""Judge for architecture_naturality environment."""
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
    require_changed_files(result, {"converter.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from converter import %%MODEL_CLASS%%

tfm = %%MODEL_CLASS%%()
tfm.eval()

checks = {{}}

# 1. Output shape correctness (length 8)
try:
    x = torch.randn(2, 8, 16)
    out = tfm(x)
    checks["basic_run"] = bool(out.shape == x.shape)
except Exception:
    checks["basic_run"] = False

# 2. Naturality Commutativity under temporal slicing (length 4)
try:
    x_large = torch.randn(2, 12, 16)
    
    # Path A: slice first, then transform
    h_then_alpha = tfm(x_large[:, :4, :])
    
    # Path B: transform first, then slice
    alpha_then_h = tfm(x_large)[:, :4, :]
    
    checks["naturality_commutes"] = bool(torch.allclose(h_then_alpha, alpha_then_h, atol=1e-5))
except Exception as e:
    checks["naturality_commutes"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        nat_ok = bool(checks.get("naturality_commutes", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "naturality_commutes", nat_ok)

        passed = sum([basic_ok, nat_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
