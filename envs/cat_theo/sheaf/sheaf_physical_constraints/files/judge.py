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

router = %%MODEL_CLASS%%(local_capacity=100.0, global_capacity=%%GLOBAL_CAP%%)
cap_global = %%GLOBAL_CAP%%

checks = {{}}

# 1. Local Consistency (Correctness on low, isolated demands)
try:
    demands = {{"node1_2": 40.0, "node2_3": 30.0}}
    allocations = router.allocate_bandwidth(demands)
    checks["local_routing_ok"] = bool(allocations.get("node1_2") == 40.0 and allocations.get("node2_3") == 30.0)
except Exception:
    checks["local_routing_ok"] = False

# 2. Local Bounds & Proportionality under Overlap constraints
try:
    # High local demand, total exceeds global capacity.
    # Demands: {"node1_2": 120.0, "node2_3": 60.0}. Total clamped is (100 + 60) = 160.
    # Since total exceeds cap_global (e.g. 150), they must be scaled proportionally.
    demands = {{"node1_2": 120.0, "node2_3": 60.0}}
    allocations = router.allocate_bandwidth(demands)
    
    a1 = allocations.get("node1_2", 0.0)
    a2 = allocations.get("node2_3", 0.0)
    
    # 1. Must be non-negative and locally bounded by 100
    bounds_ok = bool(0.0 <= a1 <= 100.0 and 0.0 <= a2 <= 100.0)
    
    # 2. Total must match cap_global
    sum_ok = bool(abs((a1 + a2) - cap_global) < 1e-4)
    
    # 3. Proportionality: since clamped local demands were 100 and 60 (ratio 5:3),
    # the outputs must maintain exactly this ratio (a1 / a2 == 5/3 == 1.666)
    ratio_ok = bool(abs((a1 / a2) - 1.6666) < 0.01)
    
    checks["local_bounds_ok"] = bool(bounds_ok and sum_ok and ratio_ok)
except Exception as e:
    checks["local_bounds_ok"] = False

# 3. Global Gluing Consistency (Proportional Scaling & Fairness under High Asymmetric Demands)
try:
    # Demands: {"node1_2": 90.0, "node2_3": 60.0, "node3_1": 90.0}. Total is 240.
    # Since total exceeds cap_global (150.0), they must be scaled proportionally.
    # Expected scaled outputs (ratio 9:6:9 -> 3:2:3):
    # Total units: 8.
    # node1_2: 150 * 3/8 = 56.25
    # node2_3: 150 * 2/8 = 37.50
    # node3_1: 150 * 3/8 = 56.25
    demands = {{"node1_2": 90.0, "node2_3": 60.0, "node3_1": 90.0}}
    allocations = router.allocate_bandwidth(demands)
    
    a1 = allocations.get("node1_2", 0.0)
    a2 = allocations.get("node2_3", 0.0)
    a3 = allocations.get("node3_1", 0.0)
    
    # Check that all keys are returned
    all_keys_present = bool(len(allocations) == 3)
    
    # Check global sum constraint
    total_bandwidth = a1 + a2 + a3
    global_ok = bool(abs(total_bandwidth - cap_global) < 1e-4)
    
    # Verify strict proportionality and symmetry
    symmetry_ok = bool(abs(a1 - a3) < 1e-4)
    ratio_ok = bool(abs(a1 - 56.25) < 0.05 and abs(a2 - 37.50) < 0.05)
    
    checks["global_backbone_ok"] = bool(all_keys_present and global_ok and symmetry_ok and ratio_ok)
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
