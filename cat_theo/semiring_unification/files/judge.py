#!/usr/bin/env python3
"""Judge for semiring_unification environment."""
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
    require_changed_files(result, {"semirings.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys
sys.path.insert(0, {workdir!r})
from semirings import %%ARITH_CLASS%%, %%TROP_CLASS%%, %%BOOL_CLASS%%
from matrix_ops import generic_matmul

checks = {{}}

# 1. Arithmetic Semiring Correctness (1/3 of score)
try:
    A = [[1.0, 2.0], [3.0, 4.0]]
    B = [[5.0, 6.0], [7.0, 8.0]]
    out = generic_matmul(A, B, %%ARITH_CLASS%%)
    checks["arithmetic_ok"] = bool(out[0][0] == 19.0 and out[1][1] == 50.0)
except Exception:
    checks["arithmetic_ok"] = False

# 2. Tropical Semiring Correctness (1/3 of score)
try:
    # Additive Identity: min(x, inf) == x
    add_id = bool(%%TROP_CLASS%%.add(5.0, %%TROP_CLASS%%.zero) == 5.0)
    
    # Multiplicative Identity: x + 0 == x
    mul_id = bool(%%TROP_CLASS%%.mul(5.0, %%TROP_CLASS%%.one) == 5.0)
    
    # Multiplication operation: 3 + 4 == 7
    op_mul = bool(%%TROP_CLASS%%.mul(3.0, 4.0) == 7.0)
    
    # Run a tropical matrix multiplication (shortest path step)
    A = [[0.0, 2.0], [%%INF_VAL%%, 0.0]]
    B = [[0.0, %%INF_VAL%%], [3.0, 0.0]]
    out = generic_matmul(A, B, %%TROP_CLASS%%)
    
    shortest_path_ok = bool(out[0][1] == 2.0 and out[1][0] == 3.0)
    
    checks["tropical_ok"] = bool(add_id and mul_id and op_mul and shortest_path_ok)
except Exception as e:
    checks["tropical_ok"] = False

# 3. Boolean Semiring Correctness (1/3 of score)
try:
    # Additive Identity: x or False == x
    add_id = bool(%%BOOL_CLASS%%.add(True, %%BOOL_CLASS%%.zero) == True and %%BOOL_CLASS%%.add(False, %%BOOL_CLASS%%.zero) == False)
    
    # Multiplicative Identity: x and True == x
    mul_id = bool(%%BOOL_CLASS%%.mul(True, %%BOOL_CLASS%%.one) == True and %%BOOL_CLASS%%.mul(False, %%BOOL_CLASS%%.one) == False)
    
    # Run a boolean matrix multiplication (transitive closure reachability step)
    A = [[True, False], [False, True]]
    B = [[False, True], [True, False]]
    out = generic_matmul(A, B, %%BOOL_CLASS%%)
    
    reachability_ok = bool(out[0][1] == True and out[1][0] == True)
    
    checks["boolean_ok"] = bool(add_id and mul_id and reachability_ok)
except Exception:
    checks["boolean_ok"] = False

import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        arith_ok = bool(checks.get("arithmetic_ok", False))
        trop_ok = bool(checks.get("tropical_ok", False))
        bool_ok = bool(checks.get("boolean_ok", False))

        mark_check(result, "arithmetic_ok", arith_ok)
        mark_check(result, "tropical_ok", trop_ok)
        mark_check(result, "boolean_ok", bool_ok)

        passed = sum([arith_ok, trop_ok, bool_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
