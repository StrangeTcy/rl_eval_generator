#!/usr/bin/env python3
"""Judge for recursive_gluing_discovery. Independent compact oracle in network.py."""
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
    build_grade_grammars,
    compact_input_bytes,
    public_grammar,
    summary_cells,
    unfolded_occurrences,
    verify_certificate,
)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
DEPTH = int("%%DEPTH%%")
INTERFACE_SIZE = int("%%INTERFACE_SIZE%%")
GLUING_REGIME = "%%GLUING_REGIME%%"
LABEL_MODE = "%%LABEL_MODE%%"
AMBIGUITY = "%%AMBIGUITY%%"
SEED = int("%%JUDGE_SEED%%")


def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"solver.py"})
    workdir, _original_files = make_workdir(patched_dir)

    items = build_grade_grammars(
        depth=DEPTH,
        interface_size=INTERFACE_SIZE,
        regime=GLUING_REGIME,
        opacity=LABEL_MODE,
        ambiguity=AMBIGUITY,
        seed=SEED,
    )
    named = dict(items)
    payload = [{"name": name, "grammar": public_grammar(grammar)} for name, grammar in items]
    # The deferred script gets its payload through argv: the generation
    # preflight allows the eval-script template to interpolate only the
    # judge workdir, so instance data must not be baked into the f-string.
    payload_path = os.path.join(workdir, "_eval_payload.json")
    with open(payload_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
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
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
outputs = []
for item in payload:
    record = {{"name": item["name"]}}
    try:
        record["first"] = solver.solve(copy.deepcopy(item["grammar"]))
        record["second"] = solver.solve(copy.deepcopy(item["grammar"]))
    except Exception as exc:
        record["error"] = type(exc).__name__ + ": " + str(exc)
    outputs.append(record)

import torch
torch.save(outputs, "eval_outputs.pt")
"""
        )

    judge_event(result, "hidden_eval", summary="running candidate on compact grammars")
    proc = run([sys.executable, eval_script, payload_path], workdir, 120, eval_env())
    if proc.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + proc.stderr[-800:])
        emit(result)

    try:
        outputs = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
    except Exception as exc:
        set_failure(result, "REWARD_DENIAL", f"Failed to read solver outputs: {exc}")
        emit(result)

    by_name = {row.get("name"): row for row in outputs if isinstance(row, dict)}
    checks = {name: False for name in CHECK_NAMES}

    try:
        for name, grammar in items:
            row = by_name.get(name, {})
            if "error" in row:
                checks[name] = False
                continue
            ok, _reason = verify_certificate(grammar, row.get("first"))
            checks[name] = ok
    except OracleBudgetExceeded as exc:
        set_failure(
            result,
            "judge_runtime_error",
            "Independent oracle exhausted its budget; this is not treated as unsat. "
            + str(exc),
        )
        emit(result)

    configured = named["configured"]
    configured_row = by_name.get("configured", {})
    try:
        first = configured_row.get("first")
        second = configured_row.get("second")
        ok, _reason = verify_certificate(configured, first)
        checks["deterministic"] = (first == second) and ok
    except Exception:
        checks["deterministic"] = False

    passed = sum(1 for name in CHECK_NAMES if checks.get(name))
    accuracy = passed / float(len(CHECK_NAMES))
    for name in CHECK_NAMES:
        mark_check(result, name, bool(checks.get(name)))

    set_metric(result, "passed_hidden_checks", passed)
    set_metric(result, "total_hidden_checks", len(CHECK_NAMES))
    set_metric(result, "compact_input_bytes", compact_input_bytes(configured))
    set_metric(result, "unfolded_occurrences", unfolded_occurrences(DEPTH))
    set_metric(result, "recursive_depth", DEPTH)
    set_metric(result, "interface_size", INTERFACE_SIZE)
    set_metric(result, "gluing_regime", GLUING_REGIME)
    set_metric(result, "label_mode", LABEL_MODE)
    set_metric(result, "ambiguity", AMBIGUITY)
    try:
        from network import compact_summaries

        set_metric(result, "summary_cells", summary_cells(compact_summaries(configured)))
    except OracleBudgetExceeded:
        set_metric(result, "summary_cells", -1)

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
