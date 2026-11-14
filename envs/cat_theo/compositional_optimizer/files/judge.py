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

# 2. Sequential recurrence, state isolation, and interleaved parameters
try:
    opt1 = MomentumStep(beta=0.9)
    opt2 = MomentumStep(beta=0.5)
    opt3 = MomentumStep(beta=0.25)
    p = torch.tensor(((1.0, 2.0), (3.0, 4.0)))
    q = torch.tensor(((8.0, 7.0), (6.0, 5.0)))
    g = torch.tensor(((0.2, -0.4), (0.6, -0.8)))
    p_before = p.clone()
    g_before = g.clone()
    v1 = opt1.update(p, g)
    v1_ref = 0.1 * g
    v2 = opt2.update(p, v1)
    v2_ref = 0.5 * v1_ref
    v3 = opt3.update(p, v2)
    v3_ref = 0.75 * v2_ref
    first_ok = int(torch.allclose(v1, v1_ref) and torch.allclose(v2, v2_ref) and torch.allclose(v3, v3_ref))
    untouched_ok = int(torch.equal(p, p_before) and torch.equal(g, g_before))
    p.add_(v3, alpha=-%%LR_VAL%%)
    p_ref = p_before - %%LR_VAL%% * v3_ref

    q_update = opt1.update(q, g * 3).clone()
    v1_next_ref = 0.9 * v1_ref + 0.1 * (p_ref * 0.2)
    v2_next_ref = 0.5 * v2_ref + 0.5 * v1_next_ref
    v3_next_ref = 0.25 * v3_ref + 0.75 * v2_next_ref
    v1_next = opt1.update(p, p * 0.2)
    v2_next = opt2.update(p, v1_next)
    v3_next = opt3.update(p, v2_next)
    p.add_(v3_next, alpha=-%%LR_VAL%%)
    p_ref = p_ref - %%LR_VAL%% * v3_next_ref
    q_next = opt1.update(q, g * -2)
    fresh = MomentumStep(beta=0.9).update(p, g)
    checks["state_isolated"] = int(
        first_ok and untouched_ok
        and torch.allclose(p, p_ref, atol=1e-6)
        and torch.allclose(v1_next, v1_next_ref, atol=1e-6)
        and torch.allclose(v2_next, v2_next_ref, atol=1e-6)
        and torch.allclose(v3_next, v3_next_ref, atol=1e-6)
        and torch.allclose(q_update, 0.3 * g, atol=1e-6)
        and torch.allclose(q_next, 0.07 * g, atol=1e-6)
        and torch.allclose(fresh, 0.1 * g, atol=1e-6)
    )
except Exception:
    checks["state_isolated"] = 0

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
