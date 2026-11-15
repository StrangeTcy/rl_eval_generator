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

# 1. Values across temperatures, ties, and large finite inputs
try:
    x = torch.tensor((-1000.0, -2.5, 0.0, 4.0, 1000.0), dtype=torch.float64).requires_grad_()
    y = torch.tensor((-998.0, -2.5, 2.0, -3.0, 999.0), dtype=torch.float64).requires_grad_()
    low = %%MODEL_CLASS%%(temperature=0.1).smooth_min(x, y)
    middle = parser.smooth_min(x, y)
    high = %%MODEL_CLASS%%(temperature=7.0).smooth_min(x, y)
    reference = torch.stack((
        -0.1 * torch.logaddexp(-x / 0.1, -y / 0.1),
        -torch.logaddexp(-x, -y),
        -7.0 * torch.logaddexp(-x / 7.0, -y / 7.0),
    ))
    outputs = torch.stack((low, middle, high))
    checks["basic_run"] = torch.isclose(
        outputs, reference, atol=%%TOLERANCE%%, rtol=%%TOLERANCE%%
    ).all().to(torch.int64).item()
except Exception:
    checks["basic_run"] = False

# 2. Exact derivatives at the same temperatures and tie cases
try:
    grad_x, grad_y = torch.autograd.grad(outputs.sum(), (x, y))
    expected_x = torch.sigmoid((y - x) / 0.1) + torch.sigmoid(y - x) + torch.sigmoid((y - x) / 7.0)
    expected_y = 3.0 - expected_x
    checks["gradient_flow_ok"] = torch.stack((
        torch.isclose(grad_x, expected_x, atol=%%TOLERANCE%%, rtol=%%TOLERANCE%%).all(),
        torch.isclose(grad_y, expected_y, atol=%%TOLERANCE%%, rtol=%%TOLERANCE%%).all(),
    )).all().to(torch.int64).item()
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
