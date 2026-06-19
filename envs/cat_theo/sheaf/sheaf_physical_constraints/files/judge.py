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
    demands = {{"route_A": 40.0, "route_B": 30.0, "route_C": 20.0}}
    allocations = router.allocate_bandwidth(demands)
    checks["local_routing_ok"] = bool(
        allocations.get("route_A") == 40.0 and 
        allocations.get("route_B") == 30.0 and 
        allocations.get("route_C") == 20.0
    )
except Exception:
    checks["local_routing_ok"] = False

# 2. Local Overlapping Switch Bounds & Proportionality (The 10/10 Sheaf overlap check)
try:
    # High local overlapping demands: route_A=120.0, route_B=60.0, route_C=0.0.
    # Switch S2 carries (route_A + route_B) = 120 (clamped to 100) + 60 = 160.
    # Since 160 exceeds local switch S2 capacity (100.0), they must be scaled locally to sum to 100.
    # Expected scaled outputs (ratio 100:60 -> 5:3):
    # route_A = 100 * 5/8 = 62.5, route_B = 100 * 3/8 = 37.5.
    demands = {{"route_A": 120.0, "route_B": 60.0, "route_C": 0.0}}
    allocations = router.allocate_bandwidth(demands)
    
    a1 = allocations.get("route_A", 0.0)
    a2 = allocations.get("route_B", 0.0)
    a3 = allocations.get("route_C", 0.0)
    
    # 1. Must be non-negative and individually bounded
    bounds_ok = bool(0.0 <= a1 <= 100.0 and 0.0 <= a2 <= 100.0 and a3 == 0.0)
    
    # 2. Overlapping Switch S2 must strictly NOT exceed 100.0
    switch_S2_ok = bool((a1 + a2) <= 100.0 + 1e-4)
    
    # 3. Proportionality: maintains the 5:3 ratio (tolerance 0.05 for minor floating-point shifts)
    ratio_ok = bool(abs((a1 / a2) - 1.6666) < 0.05)
    
    checks["local_bounds_ok"] = bool(bounds_ok and switch_S2_ok and ratio_ok)
except Exception as e:
    checks["local_bounds_ok"] = False

# 3. Global Gluing Consistency (Proportional Scaling & Fairness under High Asymmetric Overlapping Demands)
try:
    # Demands: {"route_A": 90.0, "route_B": 80.0, "route_C": 90.0}.
    # After local switch limits, total global backbone capacity (150.0) must also be respected.
    demands = {{"route_A": 90.0, "route_B": 80.0, "route_C": 90.0}}
    allocations = router.allocate_bandwidth(demands)
    
    a1 = allocations.get("route_A", 0.0)
    a2 = allocations.get("route_B", 0.0)
    a3 = allocations.get("route_C", 0.0)
    
    all_keys_present = bool(len(allocations) == 3)
    
    # 1. Check shared switch capacity limits
    S1_total = a1 + a3
    S2_total = a1 + a2
    S3_total = a2 + a3
    
    switches_ok = bool(S1_total <= 100.0 + 1e-4 and S2_total <= 100.0 + 1e-4 and S3_total <= 100.0 + 1e-4)
    
    # 2. Check global sum constraint
    total_bandwidth = a1 + a2 + a3
    global_ok = bool(total_bandwidth <= cap_global + 1e-4 and total_bandwidth > 100.0)
    
    # 3. Check symmetry: route_A and route_C have identical demands, so their allocations must be symmetric
    symmetry_ok = bool(abs(a1 - a3) < 1e-4)
    
    checks["global_backbone_ok"] = bool(all_keys_present and switches_ok and global_ok and symmetry_ok)
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
        local_ok = bool(checks.get("local_run_ok", False) or checks.get("local_routing_ok", False))
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
