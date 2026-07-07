#!/usr/bin/env python3
"""Judge for ci_dependency_graph environment."""
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
    require_changed_files(result, {"ci_machine.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random, json
sys.path.insert(0, {workdir!r})
from ci_machine import %%MODEL_CLASS%%

engine = %%MODEL_CLASS%%()
checks = {{}}

num_jobs = int("%%NUM_JOBS%%")
rng = random.Random(%%JUDGE_SEED%%)

def verify_workflow(deps, wf):
    if not isinstance(wf, dict) or len(wf) != len(deps):
        return False
    for job_id, parents in deps.items():
        name = f"job_{{job_id}}"
        if name not in wf:
            return False
        spec = wf[name]
        if not isinstance(spec, dict):
            return False
        needs = set(spec.get("needs", []))
        expected_needs = {{f"job_{{p}}" for p in parents}}
        if needs != expected_needs:
            return False
        layer = spec.get("env", {{}}).get("LAYER")
        if not isinstance(layer, int):
            return False
        if not parents:
            if layer != 0:
                return False
        else:
            max_parent = max(wf[f"job_{{p}}"]["env"]["LAYER"] for p in parents)
            if layer != max_parent + 1:
                return False
    return True

# 1. Basic structure check
try:
    deps = {{1: [], 2: [1]}}
    wf = engine.generate_workflow(deps)
    checks["workflow_structure"] = verify_workflow(deps, wf)
except Exception:
    checks["workflow_structure"] = False

# 2. Diamond DAG check
try:
    deps = {{1: [], 2: [1], 3: [1], 4: [2, 3], 5: [4]}}
    wf = engine.generate_workflow(deps)
    checks["diamond_dag"] = verify_workflow(deps, wf)
except Exception:
    checks["diamond_dag"] = False

# 3. Randomized complex DAGs seeded by JUDGE_SEED
try:
    all_ok = True
    for _ in range(15):
        n = rng.randint(4, num_jobs)
        deps = {{i: [] for i in range(1, n + 1)}}
        for i in range(2, n + 1):
            # Pick a random subset of earlier jobs
            num_parents = rng.randint(1, min(3, i - 1))
            parents = rng.sample(range(1, i), num_parents)
            deps[i] = sorted(parents)
        wf = engine.generate_workflow(deps)
        if not verify_workflow(deps, wf):
            all_ok = False
            break
    checks["randomized_scheduling"] = all_ok
except Exception:
    checks["randomized_scheduling"] = False

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
        struct_ok = bool(checks.get("workflow_structure", False))
        diam_ok = bool(checks.get("diamond_dag", False))
        rand_ok = bool(checks.get("randomized_scheduling", False))

        mark_check(result, "workflow_structure", struct_ok)
        mark_check(result, "diamond_dag", diam_ok)
        mark_check(result, "randomized_scheduling", rand_ok)

        passed = sum([struct_ok, diam_ok, rand_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
