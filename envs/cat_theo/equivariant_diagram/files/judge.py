#!/usr/bin/env python3
"""Judge for equivariant_diagram environment."""
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
    require_changed_files(result, {"layers.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
import torch.nn.functional as F
sys.path.insert(0, {workdir!r})
from layers import %%MODEL_CLASS%%
from symmetry import shift_2d

layer = %%MODEL_CLASS%%()
layer.eval()

checks = {{}}

# Helper to compute trusted circular convolution reference
def get_expected(x):
    # Circular pad 1 pixel on all sides, then apply the projection weights with zero padding (padding=0)
    x_padded = F.pad(x, (1, 1, 1, 1), mode="circular")
    return F.conv2d(x_padded, layer.proj.weight, layer.proj.bias, stride=1, padding=0)

# 1. Output shape correctness & Semantic Correctness (Not an identity/no-op hack!)
try:
    x = torch.randn(2, 16, 8, 8)
    out = layer(x)
    expected = get_expected(x)
    
    # Must match expected circular convolution AND must NOT be a simple identity return
    checks["basic_run"] = bool(out.shape == x.shape and torch.allclose(out, expected, atol=1e-4) and not torch.allclose(out, x, atol=1e-3))
except Exception as e:
    checks["basic_run"] = False

# 2. Strict translation-equivariance commutativity
try:
    x = torch.randn(4, 16, 12, 12)
    # g o f
    out_g_f = shift_2d(layer(x), shift_h=1, shift_w=2)
    # f o g
    out_f_g = layer(shift_2d(x, shift_h=1, shift_w=2))
    
    # Check if they commute (within floating point precision tolerance)
    checks["equivariance_commutes"] = bool(torch.allclose(out_g_f, out_f_g, atol=1e-4))
except Exception as e:
    checks["equivariance_commutes"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        equiv_ok = bool(checks.get("equivariance_commutes", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "equivariance_commutes", equiv_ok)

        passed = sum([basic_ok, equiv_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
