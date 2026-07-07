#!/usr/bin/env python3
"""Judge for spreadsheet_dataflow environment."""
import os
import sys
import json

from judge_lib import (base_result, emit, eval_env, judge_event, make_workdir,
                       mark_check, run, score_from_accuracy, scrub_workdir,
                       set_failure, set_metric, train_env, validate_submission,
                       require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%

def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"sheet_model.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random, re, json
sys.path.insert(0, {workdir!r})
from sheet_model import %%MODEL_CLASS%%

engine = %%MODEL_CLASS%%()
checks = {{}}

def eval_sheet(inputs, formulas):
    values = {{}}
    for i, val in enumerate(inputs):
        values[f"A{{i+1}}"] = float(val)
        
    for i in range(1, len(inputs) + 1):
        cell = f"B{{i}}"
        f_str = formulas.get(cell, "")
        if not f_str.startswith("="):
            raise ValueError(f"Cell {{cell}} does not start with '=': {{f_str!r}}")
        expr = f_str[1:]
        expr = re.sub(r'\\bMIN\\b', 'min', expr, flags=re.IGNORECASE)
        def repl(m):
            c = m.group(0).upper()
            if c in values:
                return str(values[c])
            raise ValueError(f"Unknown reference {{c}}")
        eval_expr = re.sub(r'\\b[AB]\\d+\\b', repl, expr, flags=re.IGNORECASE)
        values[cell] = float(eval(eval_expr, {{"__builtins__": None, "min": min, "max": max}}))
    return values

def reference_dp(inputs):
    res = []
    for i, v in enumerate(inputs):
        if i == 0:
            res.append(v)
        elif i == 1:
            res.append(v + res[0])
        else:
            res.append(v + min(res[i-1], res[i-2]))
    return res

grid_len = int("%%GRID_LEN%%")
rng = random.Random(%%JUDGE_SEED%%)

# 1. Formula structure check
try:
    formulas = engine.build_dp_formulas(grid_len)
    all_eq = len(formulas) == grid_len and all(str(v).startswith("=") for v in formulas.values())
    checks["formula_syntax"] = bool(all_eq)
except Exception:
    checks["formula_syntax"] = False

# 2. Basic evaluation check
try:
    test_inputs = [float(x) for x in range(1, grid_len + 1)]
    out_vals = eval_sheet(test_inputs, formulas)
    ref_vals = reference_dp(test_inputs)
    b_vals = [out_vals[f"B{{i+1}}"] for i in range(grid_len)]
    checks["basic_eval"] = bool(b_vals == ref_vals)
except Exception:
    checks["basic_eval"] = False

# 3. Randomized input invariance check seeded by JUDGE_SEED
try:
    all_ok = True
    for _ in range(15):
        rand_inputs = [rng.uniform(-100.0, 100.0) for _ in range(grid_len)]
        out = eval_sheet(rand_inputs, formulas)
        ref = reference_dp(rand_inputs)
        b_vals = [out[f"B{{i+1}}"] for i in range(grid_len)]
        if any(abs(b - r) > 1e-4 for b, r in zip(b_vals, ref)):
            all_ok = False
            break
    checks["randomized_invariance"] = all_ok
except Exception:
    checks["randomized_invariance"] = False

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
        syn_ok = bool(checks.get("formula_syntax", False))
        basic_ok = bool(checks.get("basic_eval", False))
        rand_ok = bool(checks.get("randomized_invariance", False))

        mark_check(result, "formula_syntax", syn_ok)
        mark_check(result, "basic_eval", basic_ok)
        mark_check(result, "randomized_invariance", rand_ok)

        passed = sum([syn_ok, basic_ok, rand_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
