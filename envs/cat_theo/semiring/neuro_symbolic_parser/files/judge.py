#!/usr/bin/env python3
"""Judge for neuro_symbolic_parser environment."""
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
    require_changed_files(result, {"parser.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from parser import %%MODEL_CLASS%%

parser = %%MODEL_CLASS%%(temperature=1.0)
parser.eval()

checks = {{}}

# 1. Output shape correctness
try:
    x = torch.tensor([1.5], requires_grad=True)
    y = torch.tensor([3.7], requires_grad=True)
    out = parser.smooth_min(x, y)
    checks["basic_run"] = bool(out.shape == (1,))
except Exception:
    checks["basic_run"] = False

# 2. Strict Gradient Flow (Contravariant Pullback on LSE Semiring)
try:
    x = torch.tensor([1.5], requires_grad=True)
    y = torch.tensor([2.5], requires_grad=True)
    
    out = parser.smooth_min(x, y)
    loss = out.sum()
    loss.backward()
    
    # Under correct LSE implementation, both x.grad and y.grad must be non-zero
    grad_x_ok = bool(x.grad is not None and float(x.grad.item()) > 0.1)
    grad_y_ok = bool(y.grad is not None and float(y.grad.item()) > 0.1)
    
    # Calculate target theoretical gradients under Log-Sum-Exp:
    # d(LSE)/dx = exp(-x) / (exp(-x) + exp(-y))
    # exp(-1.5) / (exp(-1.5) + exp(-2.5)) = 0.2231 / (0.2231 + 0.082) = 0.731
    target_grad_x = 0.731
    val_match = bool(abs(float(x.grad.item()) - target_grad_x) < 0.02)
    
    checks["gradient_flow_ok"] = bool(grad_x_ok and grad_y_ok and val_match)
except Exception as e:
    checks["gradient_flow_ok"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        grad_ok = bool(checks.get("gradient_flow_ok", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "gradient_flow_ok", grad_ok)

        passed = sum([basic_ok, grad_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
