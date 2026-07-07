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

# 1. AST Check: verify regex mechanisms are used and reject host-language indexing/loops over characters
try:
    with open(os.path.join({workdir!r}, "regex_machine.py"), "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    re_found = False
    forbidden_indexing = False
    forbidden_loop = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and getattr(node.value, "id", "") == "re":
            re_found = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("sub", "subn", "finditer", "findall", "match", "search"):
            re_found = True
            
        if isinstance(node, ast.FunctionDef) and node.name == "step":
            arg_names = {{arg.arg for arg in node.args.args}}
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Subscript) and isinstance(subnode.value, ast.Name) and subnode.value.id in arg_names:
                    forbidden_indexing = True
                if isinstance(subnode, ast.For) and isinstance(subnode.iter, ast.Call) and isinstance(subnode.iter.func, ast.Name) and subnode.iter.func.id == "range":
                    forbidden_loop = True
    checks["regex_used"] = bool(re_found and not forbidden_indexing and not forbidden_loop)
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

# 3. Randomized length preservation & OOD accuracy checks seeded by JUDGE_SEED with TraceForensics
try:
    test_strings = ["".join(rng.choice(["0", "1"]) for _ in range(string_len)) for _ in range(15)]
    length_ok = True
    all_ok = True
    forensics = None
    for s in test_strings:
        out = engine.step(s)
        ref = reference_step(s)
        if len(out) != len(s):
            length_ok = False
        if out != ref:
            all_ok = False
            padded = "0" + s + "0"
            failed_neighborhoods = set()
            boundary_fail = None
            if len(out) != len(s):
                boundary_fail = f"length mismatch (in={{len(s)}}, out={{len(out)}})"
            else:
                for i in range(len(s)):
                    if out[i] != ref[i]:
                        nb = padded[i:i+3]
                        failed_neighborhoods.add(f"{{nb}}->{{ref[i]}} (got {{out[i]}})")
                        if i == 0:
                            boundary_fail = "left boundary neighborhood"
                        elif i == len(s) - 1:
                            boundary_fail = "right boundary neighborhood"
            if forensics is None:
                forensics = {
                    "failed_rules": sorted(failed_neighborhoods),
                    "boundary_collapse": boundary_fail,
                }
    checks["length_preservation"] = length_ok
    checks["randomized_accuracy"] = all_ok
    checks["forensics"] = forensics
except Exception:
    checks["length_preservation"] = False
    checks["randomized_accuracy"] = False
    checks["forensics"] = None

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
        len_ok = bool(checks.get("length_preservation", False))
        acc_ok = bool(checks.get("randomized_accuracy", False))
        forensics = checks.get("forensics")

        mark_check(result, "regex_used", reg_ok)
        mark_check(result, "basic_step", basic_ok)
        mark_check(result, "length_preservation", len_ok)
        mark_check(result, "randomized_accuracy", acc_ok)
        if forensics:
            set_metric(result, "trace_forensics", forensics)
            notes_msg = "Morphism Error Report: "
            if forensics.get("boundary_collapse"):
                notes_msg += f"Collapsed on {forensics['boundary_collapse']}. "
            if forensics.get("failed_rules"):
                notes_msg += f"Rule transition failed on: {', '.join(forensics['failed_rules'])}."
            result.setdefault("notes", []).append(notes_msg)

        passed = sum([reg_ok, basic_ok, len_ok, acc_ok])
        accuracy = passed / 4.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
