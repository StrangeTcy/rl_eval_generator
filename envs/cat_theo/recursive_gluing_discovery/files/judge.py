#!/usr/bin/env python3
"""Judge for recursive_gluing_discovery. Candidate sees public views only."""
import json
import os
import sys

import torch

from judge_lib import (
    base_result,
    emit,
    eval_env,
    judge_event,
    make_workdir,
    mark_check,
    require_changed_files,
    run,
    score_from_accuracy,
    set_failure,
    set_metric,
    validate_submission,
)
from network import (
    CHECK_NAMES,
    OracleBudgetExceeded,
    build_grade_bundles,
    cartesian_size,
    complete_pair_count,
    evaluate_against_complete,
    listed_pair_count,
    parse_solve_output,
)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
DEPTH = int("%%DEPTH%%")
DOMAIN_SIZE = int("%%DOMAIN_SIZE%%")
GLUING_REGIME = "%%GLUING_REGIME%%"
TRANSPORT_FAMILY = "%%TRANSPORT_FAMILY%%"
SEED = int("%%JUDGE_SEED%%")


def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"solver.py"})
    workdir, _original_files = make_workdir(patched_dir)

    items = build_grade_bundles(
        depth=DEPTH,
        domain_size=DOMAIN_SIZE,
        regime=GLUING_REGIME,
        family=TRANSPORT_FAMILY,
        seed=SEED,
    )
    named = dict(items)
    payload = [{"name": name, "public": bundle["public"]} for name, bundle in items]
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as handle:
        handle.write(
            f"""
import copy
import json
import sys
sys.path.insert(0, {workdir!r})
from solver import %%MODEL_CLASS%%

solver = %%MODEL_CLASS%%()
payload = json.loads({json.dumps(payload)!r})
outputs = []
for item in payload:
    record = {{"name": item["name"]}}
    try:
        record["first"] = solver.solve(copy.deepcopy(item["public"]))
        record["second"] = solver.solve(copy.deepcopy(item["public"]))
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)
    outputs.append(record)

import torch
torch.save(outputs, "eval_outputs.pt")
"""
        )

    judge_event(result, "hidden_eval", summary="running candidate on public views")
    proc = run([sys.executable, eval_script], workdir, 120, eval_env())
    if proc.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + proc.stderr[-800:])
        emit(result)

    try:
        outputs = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=False)
    except Exception as exc:
        set_failure(result, "REWARD_DENIAL", f"Failed to read solver outputs: {exc}")
        emit(result)

    by_name = {row.get("name"): row for row in outputs if isinstance(row, dict)}
    checks = {name: False for name in CHECK_NAMES}

    def _callable_for(row):
        def _solve(_public):
            if "error" in row:
                raise RuntimeError(row["error"])
            return row.get("first")

        return _solve

    try:
        for name, bundle in items:
            row = by_name.get(name, {})
            if "error" in row:
                checks[name] = False
                continue
            checks[name] = evaluate_against_complete(
                _callable_for(row), bundle["public"], bundle["complete"]
            )
    except OracleBudgetExceeded as exc:
        set_failure(
            result,
            "judge_runtime_error",
            "Independent oracle exhausted its search budget; this is not treated as unsat. "
            + str(exc),
        )
        emit(result)

    configured = named["configured"]
    configured_row = by_name.get("configured", {})
    try:
        first = configured_row.get("first")
        second = configured_row.get("second")
        parsed, err = parse_solve_output(configured["complete"], first)
        checks["deterministic"] = (first == second) and parsed is not None and not err
    except Exception:
        checks["deterministic"] = False

    passed = sum(1 for name in CHECK_NAMES if checks.get(name))
    accuracy = passed / float(len(CHECK_NAMES))
    for name in CHECK_NAMES:
        mark_check(result, name, bool(checks.get(name)))

    set_metric(result, "passed_hidden_checks", passed)
    set_metric(result, "total_hidden_checks", len(CHECK_NAMES))
    set_metric(result, "configured_cartesian_size", cartesian_size(configured["complete"]))
    set_metric(result, "listed_pair_count", listed_pair_count(configured["public"]))
    set_metric(result, "complete_pair_count", complete_pair_count(configured["complete"]))
    set_metric(result, "gluing_regime", GLUING_REGIME)
    set_metric(result, "transport_family", TRANSPORT_FAMILY)
    set_metric(result, "recursive_depth", DEPTH)
    set_metric(result, "domain_size", DOMAIN_SIZE)

    result["training_completed"] = True
    result["model_saved"] = True
    score_from_accuracy(
        result,
        accuracy,
        PASS_THRESHOLD,
        PARTIAL_THRESHOLD,
        anti_gaming_passed=True,
    )
    emit(result)


if __name__ == "__main__":
    main()
