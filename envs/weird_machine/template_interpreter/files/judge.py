#!/usr/bin/env python3
"""Judge for template_interpreter environment."""
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
    require_changed_files(result, {"template_machine.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random, json, jinja2
sys.path.insert(0, {workdir!r})
from template_machine import %%MODEL_CLASS%%

engine = %%MODEL_CLASS%%()
checks = {{}}

max_items = int("%%MAX_ITEMS%%")
rng = random.Random(%%JUDGE_SEED%%)

def reference_decode(ops):
    res = []
    for op in ops:
        if not op.get("skip", False):
            res.append(str(op.get("symbol", "")) * int(op.get("repeat", 0)))
    return "".join(res)

# 1. Template syntax structure check
try:
    tpl_str = engine.get_template()
    has_tags = isinstance(tpl_str, str) and ("{{%" in tpl_str or "{{{{" in tpl_str)
    checks["template_syntax"] = bool(has_tags)
except Exception:
    checks["template_syntax"] = False

# 2. Basic visible rendering check
try:
    ops = [
        {{"symbol": "Y", "repeat": 2, "skip": False}},
        {{"symbol": "Z", "repeat": 10, "skip": True}},
        {{"symbol": "K", "repeat": 4, "skip": False}}
    ]
    out = jinja2.Template(tpl_str).render(operations=ops).strip()
    checks["basic_render"] = bool(out == "YYKKKK")
except Exception:
    checks["basic_render"] = False

# 3. Randomized complex run-length decoding seeded by JUDGE_SEED
try:
    all_ok = True
    for _ in range(15):
        ops = []
        for _ in range(rng.randint(5, max_items)):
            sym = rng.choice(["A", "B", "C", "D", "#", "9"])
            rep = rng.randint(0, 6)
            skp = rng.choice([True, False])
            ops.append({{"symbol": sym, "repeat": rep, "skip": skp}})
        out = jinja2.Template(tpl_str).render(operations=ops).strip()
        ref = reference_decode(ops)
        if out != ref:
            all_ok = False
            break
    checks["randomized_rendering"] = all_ok
except Exception:
    checks["randomized_rendering"] = False

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
        syn_ok = bool(checks.get("template_syntax", False))
        basic_ok = bool(checks.get("basic_render", False))
        rand_ok = bool(checks.get("randomized_rendering", False))

        mark_check(result, "template_syntax", syn_ok)
        mark_check(result, "basic_render", basic_ok)
        mark_check(result, "randomized_rendering", rand_ok)

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
