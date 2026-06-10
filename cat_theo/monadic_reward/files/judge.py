#!/usr/bin/env python3
"""Judge for monadic_reward environment."""
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
    require_changed_files(result, {"agent_code.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys
sys.path.insert(0, {workdir!r})
from monad import StateMonad
from agent_code import %%MODEL_CLASS%%
import agent_code

verifier = %%MODEL_CLASS%%()

checks = {{}}

# 1. Output value correctness
try:
    m = verifier.compute(10)
    val, state = m.run_fn([])
    checks["basic_run"] = bool(val == 11)
except Exception:
    checks["basic_run"] = False

# 2. Strict Monadic State Encapsulation (Anti-Cheat / Purity checking)
try:
    # Reset any global log if it exists
    if hasattr(agent_code, "GLOBAL_LOG"):
        agent_code.GLOBAL_LOG = []
        
    m = verifier.compute(42)
    
    # Thread the state starting with empty list []
    val, state = m.run_fn([])
    
    # Under correct implementation, the state log is modified inside the monad,
    # and the global GLOBAL_LOG is completely untouched (empty []).
    state_ok = bool(state == ["processed 42"])
    
    global_untouched = True
    if hasattr(agent_code, "GLOBAL_LOG") and len(agent_code.GLOBAL_LOG) > 0:
        global_untouched = False
        
    checks["monadic_purity"] = bool(state_ok and global_untouched)
except Exception as e:
    checks["monadic_purity"] = False

import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        purity_ok = bool(checks.get("monadic_purity", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "monadic_purity", purity_ok)

        passed = sum([basic_ok, purity_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
