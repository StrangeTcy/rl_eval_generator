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

# 2. Strict Constraint Integrity Verification (Anti-Cheat / No Bypass)
try:
    # We must verify that the agent did NOT delete, disable, or relax the foreign keys.
    # We open a fresh connection and run PRAGMA foreign_key_check.
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Enable foreign keys and verify that they are structurally registered in SQLite
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Query foreign key list on all three tables
    fk_users = cursor.execute("PRAGMA foreign_key_list(users);").fetchall()
    fk_txs = cursor.execute("PRAGMA foreign_key_list(transactions);").fetchall()
    fk_addr = cursor.execute("PRAGMA foreign_key_list(addresses);").fetchall()
    
    # Each table must have exactly 1 active foreign key reference
    structural_constraints_ok = bool(len(fk_users) == 1 and len(fk_txs) == 1 and len(fk_addr) == 1)
    
    # Assert they reference the correct tables
    # fk_users -> addresses, fk_txs -> users, fk_addr -> transactions
    ref_users = fk_users[0][2] == "addresses"
    ref_txs = fk_txs[0][2] == "users"
    ref_addr = fk_addr[0][2] == "transactions"
    
    checks["constraints_preserved"] = bool(structural_constraints_ok and ref_users and ref_txs and ref_addr)
    conn.close()
except Exception as e:
    checks["constraints_preserved"] = False

# 3. Global Gluing Consistency (Symmetric transaction handles circular bounds)
try:
    # Attempt to insert a full circular microservice record
    mig.insert_transaction(db_path, t_id=101, u_id=202, a_id=303, amount=99.9)
    
    # Verify the insertion is complete, circular references are valid, and foreign keys are intact
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Check that all records exist and relate to each other
    cursor.execute("SELECT address_id FROM users WHERE id=202;")
    addr_id = cursor.fetchone()[0]
    
    cursor.execute("SELECT user_id, amount FROM transactions WHERE id=101;")
    user_row = cursor.fetchone()
    
    cursor.execute("SELECT transaction_id FROM addresses WHERE id=303;")
    tx_id = cursor.fetchone()[0]
    
    # Run PRAGMA foreign_key_check to ensure no foreign key constraint is currently broken!
    fk_check_result = cursor.execute("PRAGMA foreign_key_check;").fetchall()
    fk_clean = bool(len(fk_check_result) == 0)
    
    checks["global_gluing_ok"] = bool(
        addr_id == 303 and 
        user_row is not None and user_row[0] == 202 and float(user_row[1]) == 99.9 and 
        tx_id == 101 and 
        fk_clean
    )
    conn.close()
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
        const_ok = bool(checks.get("constraints_preserved", False))
        global_ok = bool(checks.get("global_gluing_ok", False))

        mark_check(result, "local_schema_ok", local_ok)
        mark_check(result, "constraints_preserved", const_ok)
        mark_check(result, "global_gluing_ok", global_ok)

        passed = sum([local_ok, const_ok, global_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
