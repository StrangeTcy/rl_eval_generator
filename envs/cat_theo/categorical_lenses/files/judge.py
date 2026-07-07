#!/usr/bin/env python3
"""Judge for categorical_lenses environment."""
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
    require_changed_files(result, {"lenses.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random
sys.path.insert(0, {workdir!r})
from lenses import %%MODEL_CLASS%%

lens = %%MODEL_CLASS%%()

checks = {{}}

# Dynamically randomize state and feature inputs to prevent static hardcoding/overfitting hacks
rng = random.Random(%%JUDGE_SEED%%)
s = (rng.uniform(-100.0, 100.0), rng.uniform(-100.0, 100.0))
a = rng.uniform(-100.0, 100.0)
a_prime = rng.uniform(-100.0, 100.0)

# 1. Put-Get Law: view(update(s, a)) == a
try:
    s_updated = lens.update(s, a)
    v = lens.view(s_updated)
    checks["put_get"] = bool(abs(v - a) < 1e-5)
except Exception:
    checks["put_get"] = False

# 2. Get-Put Law: update(s, view(s)) == s
try:
    v = lens.view(s)
    s_restored = lens.update(s, v)
    checks["get_put"] = bool(abs(s_restored[0] - s[0]) < 1e-5 and abs(s_restored[1] - s[1]) < 1e-5)
except Exception:
    checks["get_put"] = False

# 3. Put-Put Law: update(update(s, a), a_prime) == update(s, a_prime)
try:
    s_double = lens.update(lens.update(s, a), a_prime)
    s_single = lens.update(s, a_prime)
    checks["put_put"] = bool(abs(s_double[0] - s_single[0]) < 1e-5 and abs(s_double[1] - s_single[1]) < 1e-5)
except Exception:
    checks["put_put"] = False

import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        pg_ok = bool(checks.get("put_get", False))
        gp_ok = bool(checks.get("get_put", False))
        pp_ok = bool(checks.get("put_put", False))

        mark_check(result, "put_get", pg_ok)
        mark_check(result, "get_put", gp_ok)
        mark_check(result, "put_put", pp_ok)

        passed = sum([pg_ok, gp_ok, pp_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
