#!/usr/bin/env python3
"""Judge for css_state_machine environment."""
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
    require_changed_files(result, {"css_logic.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random, re, json
sys.path.insert(0, {workdir!r})
from css_logic import %%MODEL_CLASS%%

engine = %%MODEL_CLASS%%()
checks = {{}}

def eval_css_logic(rules, checked_indices, n):
    computed = {{"#out_even": "none", "#out_odd": "none"}}
    for selector, decl in rules:
        parts = [p.strip() for p in selector.split("~")]
        target = parts[-1]
        if target not in computed:
            continue
        match = True
        for cond in parts[:-1]:
            m = re.match(r"^#c(\\d+)(:(not\\(:\\s*)?checked(\\))?)?$", cond)
            if not m:
                match = False
                break
            idx = int(m.group(1))
            is_negated = "not" in cond
            is_checked = idx in checked_indices
            if is_negated and is_checked:
                match = False
                break
            if not is_negated and not is_checked:
                match = False
                break
        if match:
            computed[target] = decl.get("display", "none")
    return computed

num_bits = int("%%NUM_BITS%%")
rng = random.Random(%%JUDGE_SEED%%)

# 1. Rule syntax and structure check
try:
    rules = engine.generate_parity_rules(num_bits)
    is_valid = isinstance(rules, list) and len(rules) > 0
    for sel, decl in rules:
        if not isinstance(sel, str) or "~" not in sel or not isinstance(decl, dict):
            is_valid = False
    checks["rule_structure"] = bool(is_valid)
except Exception:
    checks["rule_structure"] = False

# 2. Exhaustive or randomized parity check seeded by JUDGE_SEED
try:
    all_ok = True
    for mask in range(1 << num_bits):
        checked = {{i for i in range(num_bits) if (mask & (1 << i))}}
        parity_odd = (len(checked) % 2 == 1)
        out = eval_css_logic(rules, checked, num_bits)
        if parity_odd:
            if out["#out_odd"] != "block" or out["#out_even"] == "block":
                all_ok = False
                break
        else:
            if out["#out_even"] != "block" or out["#out_odd"] == "block":
                all_ok = False
                break
    checks["parity_correctness"] = bool(all_ok)
except Exception:
    checks["parity_correctness"] = False

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
        struct_ok = bool(checks.get("rule_structure", False))
        parity_ok = bool(checks.get("parity_correctness", False))

        mark_check(result, "rule_structure", struct_ok)
        mark_check(result, "parity_correctness", parity_ok)

        passed = sum([struct_ok, parity_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
