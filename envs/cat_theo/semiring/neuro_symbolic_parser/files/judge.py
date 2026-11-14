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

# 1. Values, ties, large magnitudes, and temperature dependence
try:
    x = torch.tensor((1.5, 0.0, 10000.0, -10000.0), dtype=torch.float64)
    y = torch.tensor((2.5, 0.0, 10001.0, -9999.0), dtype=torch.float64)
    out = parser.smooth_min(x, y)
    cold = %%MODEL_CLASS%%(temperature=0.25).smooth_min(x, y)
    warm = %%MODEL_CLASS%%(temperature=3.0).smooth_min(x, y)
    checks["basic_run"] = int(
        out.shape == x.shape and cold.shape == x.shape and warm.shape == x.shape
        and torch.allclose(out, -torch.logaddexp(-x, -y), atol=%%TOLERANCE%%, rtol=0)
        and torch.allclose(cold, -0.25 * torch.logaddexp(-x / 0.25, -y / 0.25), atol=%%TOLERANCE%%, rtol=0)
        and torch.allclose(warm, -3.0 * torch.logaddexp(-x / 3.0, -y / 3.0), atol=%%TOLERANCE%%, rtol=0)
    )
except Exception:
    checks["basic_run"] = 0

# 2. Derivatives at unequal inputs, ties, and extreme magnitudes
try:
    x = torch.tensor((1.5, 0.0, 10000.0, -10000.0), dtype=torch.float64).requires_grad_()
    y = torch.tensor((2.5, 0.0, 10001.0, -9999.0), dtype=torch.float64).requires_grad_()
    out = %%MODEL_CLASS%%(temperature=3.0).smooth_min(x, y)
    out.sum().backward()
    checks["gradient_flow_ok"] = int(
        torch.allclose(x.grad, torch.sigmoid((y - x) / 3.0), atol=%%TOLERANCE%%, rtol=%%TOLERANCE%%)
        and torch.allclose(y.grad, torch.sigmoid((x - y) / 3.0), atol=%%TOLERANCE%%, rtol=%%TOLERANCE%%)
    )
except Exception:
    checks["gradient_flow_ok"] = 0

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
