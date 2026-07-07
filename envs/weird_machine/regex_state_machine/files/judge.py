#!/usr/bin/env python3
"""Judge for regex_state_machine environment."""
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
    require_changed_files(result, {"regex_machine.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random, ast
sys.path.insert(0, {workdir!r})
from regex_machine import %%MODEL_CLASS%%

engine = %%MODEL_CLASS%%()

checks = {{}}

# Reference Rule 110 implementation
def reference_step(s: str) -> str:
    padded = "0" + s + "0"
    res = []
    rule = {{"111": "0", "110": "1", "101": "1", "100": "0", "011": "1", "010": "1", "001": "1", "000": "0"}}
    for i in range(len(s)):
        nb = padded[i:i+3]
        res.append(rule[nb])
    return "".join(res)

rng = random.Random(%%JUDGE_SEED%%)
string_len = int("%%STRING_LEN%%")

# 1. AST Check: verify regex mechanisms are used rather than raw character indexing loops
try:
    with open(os.path.join({workdir!r}, "regex_machine.py"), "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    # Check if 're' module calls or regex methods are present
    re_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and getattr(node.value, "id", "") == "re":
            re_found = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("sub", "subn", "finditer", "findall", "match", "search"):
            re_found = True
    checks["regex_used"] = re_found
except Exception:
    checks["regex_used"] = False

# 2. Non-identity & Basic step correctness
try:
    test_str = "00110101"
    out = engine.step(test_str)
    ref = reference_step(test_str)
    checks["basic_step"] = bool(out == ref and out != test_str)
except Exception:
    checks["basic_step"] = False

# 3. Randomized OOD length checks seeded by JUDGE_SEED
try:
    all_ok = True
    for _ in range(15):
        s = "".join(rng.choice(["0", "1"]) for _ in range(string_len))
        if engine.step(s) != reference_step(s):
            all_ok = False
            break
    checks["randomized_accuracy"] = all_ok
except Exception:
    checks["randomized_accuracy"] = False

import json
with open("eval_outputs.json", "w") as f_out:
    json.dump(checks, f_out)
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        with open(os.path.join(workdir, "eval_outputs.json"), "r", encoding="utf-8") as f_in:
            checks = json.load(f_in)
        reg_ok = bool(checks.get("regex_used", False))
        basic_ok = bool(checks.get("basic_step", False))
        acc_ok = bool(checks.get("randomized_accuracy", False))

        mark_check(result, "regex_used", reg_ok)
        mark_check(result, "basic_step", basic_ok)
        mark_check(result, "randomized_accuracy", acc_ok)

        passed = sum([reg_ok, basic_ok, acc_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
