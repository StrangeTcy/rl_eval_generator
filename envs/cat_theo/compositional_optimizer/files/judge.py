#!/usr/bin/env python3
"""Judge for compositional_optimizer environment."""
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
    require_changed_files(result, {"optimizer.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from optimizer import MomentumStep

checks = {{}}

# 1. Output shape correctness
try:
    opt = MomentumStep()
    p = torch.randn(2, 2)
    g = torch.randn(2, 2)
    out = opt.update(p, g)
    checks["basic_run"] = bool(out.shape == p.shape)
except Exception:
    checks["basic_run"] = False

# 2. Three modules, three steps, regrouped calls, and independent parameters
try:
    a = MomentumStep(beta=0.8)
    b = MomentumStep(beta=0.6)
    c = MomentumStep(beta=0.4)
    aa = MomentumStep(beta=0.8)
    bb = MomentumStep(beta=0.6)
    cc = MomentumStep(beta=0.4)
    p = torch.arange(4, dtype=torch.float64).reshape(2, 2)
    q = p.clone()
    g1 = torch.ones_like(p)
    g2 = -2.0 * torch.ones_like(p)
    g3 = torch.arange(4, dtype=torch.float64).reshape(2, 2) + 0.5
    inputs_before = torch.stack((p, q, g1, g2, g3)).clone()
    r_a1 = 0.2 * g1
    r_b1 = 0.4 * r_a1
    r_c1 = 0.6 * r_b1
    r_a2 = 0.8 * r_a1 + 0.2 * g2
    r_b2 = 0.6 * r_b1 + 0.4 * r_a2
    r_c2 = 0.4 * r_c1 + 0.6 * r_b2
    r_a3 = 0.8 * r_a2 + 0.2 * g3
    r_b3 = 0.6 * r_b2 + 0.4 * r_a3
    r_c3 = 0.4 * r_c2 + 0.6 * r_b3
    left1 = c.update(p, b.update(p, a.update(p, g1))).clone()
    mid1 = bb.update(p, aa.update(p, g1))
    right1 = cc.update(p, mid1).clone()
    left2 = c.update(p, b.update(p, a.update(p, g2))).clone()
    mid2 = bb.update(p, aa.update(p, g2))
    right2 = cc.update(p, mid2).clone()
    independent = c.update(q, b.update(q, a.update(q, g3))).clone()
    left3 = c.update(p, b.update(p, a.update(p, g3))).clone()
    mid3 = bb.update(p, aa.update(p, g3))
    right3 = cc.update(p, mid3).clone()
    measured = torch.stack((left1, right1, left2, right2, left3, right3, independent))
    expected = torch.stack((r_c1, r_c1, r_c2, r_c2, r_c3, r_c3, 0.048 * g3))
    checks["state_isolated"] = (
        torch.isclose(measured, expected, atol=1e-8, rtol=1e-6).all().to(torch.int64)
        * torch.isclose(torch.stack((p, q, g1, g2, g3)), inputs_before, atol=0, rtol=0).all().to(torch.int64)
    ).item()
except Exception as e:
    checks["state_isolated"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        assoc_ok = bool(checks.get("state_isolated", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "state_isolated", assoc_ok)

        passed = sum([basic_ok, assoc_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
