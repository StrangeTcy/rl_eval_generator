#!/usr/bin/env python3
"""Judge for sheaf_physical_constraints environment."""
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
    require_changed_files(result, {"route.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys
sys.path.insert(0, {workdir!r})
from route import %%MODEL_CLASS%%

router = %%MODEL_CLASS%%(local_capacity=100.0, global_capacity=150.0)

checks = {{}}

# 1. Local Consistency (Correctness on low, isolated demands)
try:
    demands = {{"node1_2": 40.0, "node2_3": 30.0}}
    allocations = router.allocate_bandwidth(demands)
    checks["local_routing_ok"] = bool(allocations.get("node1_2") == 40.0 and allocations.get("node2_3") == 30.0)
except Exception:
    checks["local_routing_ok"] = False

# 2. Overlap/Intersection Consistency (Respects individual switch bounds under high demands)
try:
    demands = {{"node1_2": 120.0, "node2_3": 80.0}}
    allocations = router.allocate_bandwidth(demands)
    checks["local_bounds_ok"] = bool(allocations.get("node1_2") <= 100.0 and allocations.get("node2_3") == 80.0)
except Exception:
    checks["local_bounds_ok"] = False

# 3. Global Gluing Consistency (Maintains aggregate global backbone constraint)
try:
    demands = {{"node1_2": 90.0, "node2_3": 80.0, "node3_1": 90.0}}
    allocations = router.allocate_bandwidth(demands)
    
    total_bandwidth = sum(allocations.values())
    
    # Check that aggregate bandwidth strictly does NOT exceed global backbone capacity (150.0)
    global_ok = bool(total_bandwidth <= 150.0 + 1e-4)
    
    # Check that allocation isn't trivially zeroed out (preserving routing utility)
    preserved_ok = bool(total_bandwidth > 100.0)
    
    checks["global_backbone_ok"] = bool(global_ok and preserved_ok)
except Exception as e:
    checks["global_backbone_ok"] = False

import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        local_ok = bool(checks.get("local_routing_ok", False))
        bounds_ok = bool(checks.get("local_bounds_ok", False))
        global_ok = bool(checks.get("global_backbone_ok", False))

        mark_check(result, "local_routing_ok", local_ok)
        mark_check(result, "local_bounds_ok", bounds_ok)
        mark_check(result, "global_backbone_ok", global_ok)

        passed = sum([local_ok, bounds_ok, global_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
