#!/usr/bin/env python3
"""Judge for sheaf_schema_sync environment."""
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
    require_changed_files(result, {"migration.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, os, sqlite3
sys.path.insert(0, {workdir!r})
from migration import %%MODEL_CLASS%%

db_path = "test_judge.db"
if os.path.exists(db_path):
    os.remove(db_path)

mig = %%MODEL_CLASS%%()

checks = {{}}

# 1. Local Consistency (Schema can be created)
try:
    mig.create_schema(db_path)
    checks["local_schema_ok"] = os.path.exists(db_path)
except Exception:
    checks["local_schema_ok"] = False

# 2. Global Gluing Consistency (Symmetric transaction handles circular bounds)
try:
    # Attempt to insert a full circular microservice record:
    # Transaction -> User -> Address -> Transaction
    mig.insert_transaction(db_path, t_id=101, u_id=202, a_id=303, amount=99.9)
    
    # Verify the insertion is complete and matches
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM transactions WHERE id=101;")
    row = cursor.fetchone()
    conn.close()
    
    checks["global_gluing_ok"] = bool(row is not None and float(row[0]) == 99.9)
except Exception as e:
    checks["global_gluing_ok"] = False

if os.path.exists(db_path):
    os.remove(db_path)

import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        local_ok = bool(checks.get("local_schema_ok", False))
        global_ok = bool(checks.get("global_gluing_ok", False))

        mark_check(result, "local_schema_ok", local_ok)
        mark_check(result, "global_gluing_ok", global_ok)

        passed = sum([local_ok, global_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
