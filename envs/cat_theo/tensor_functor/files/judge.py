#!/usr/bin/env python3
"""Judge for tensor_functor environment."""
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
    require_changed_files(result, {"model.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from model import %%MODEL_CLASS%%

model = %%MODEL_CLASS%%(dim=16)
model.eval()

checks = {{}}

# 1. Output shape & type correctness
try:
    x = torch.randn(2, 16, 8, 8)
    out = model(x)
    checks["basic_run"] = bool(out.shape == x.shape)
except Exception:
    checks["basic_run"] = False

# 2. Functorial Naturality under vmap
try:
    x_batch = torch.randn(3, 2, 16, 8, 8)
    # vmap the forward pass over the outer dimension
    vmapped_fn = torch.vmap(model)
    out_vmap = vmapped_fn(x_batch)
    checks["vmap_naturality"] = bool(out_vmap.shape == x_batch.shape)
except Exception as e:
    checks["vmap_naturality"] = False

# 3. Dynamic input spatial dimensions (eliminating the Coordinate Trap)
try:
    x_large = torch.randn(2, 16, 12, 12)
    out_large = model(x_large)
    checks["dynamic_spatial"] = bool(out_large.shape == x_large.shape)
except Exception:
    checks["dynamic_spatial"] = False

# 4. Functorial Naturality under Differentiation (Contravariant Pullback)
try:
    x_grad = torch.randn(2, 16, 8, 8, requires_grad=True)
    out_grad = model(x_grad)
    loss = out_grad.sum()
    loss.backward()
    # Check that gradient flows perfectly back to input and is non-trivial (non-zero)
    checks["jacobian_naturality"] = bool(x_grad.grad is not None and torch.norm(x_grad.grad) > 1e-4)
except Exception:
    checks["jacobian_naturality"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        vmap_ok = bool(checks.get("vmap_naturality", False))
        dynamic_ok = bool(checks.get("dynamic_spatial", False))
        jac_ok = bool(checks.get("jacobian_naturality", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "vmap_naturality", vmap_ok)
        mark_check(result, "dynamic_spatial", dynamic_ok)
        mark_check(result, "jacobian_naturality", jac_ok)

        passed = sum([basic_ok, vmap_ok, dynamic_ok, jac_ok])
        accuracy = passed / 4.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
