#!/usr/bin/env python3
"""Judge for the secondary parse-only solver track."""
from __future__ import annotations

import re
import sys

from judge_lib import (
    base_result,
    emit,
    make_workdir,
    mark_check,
    require_changed_files,
    set_failure,
    validate_submission,
)

TOTAL_CHECKS = %%SCORING_TOTAL_CHECKS%%


def expected_parse(spec_text: str) -> str:
    """Parse the restricted relay DSL as data, never as Python source."""
    if "format: flat-relay-v1" in spec_text:
        rules = re.findall(
            r"^-\s+([^()\s]+)\(payload\)\s*->\s*([^()\s]+)\((.+)\)\s*$",
            spec_text,
            re.M,
        )
        if len(rules) != 3:
            raise ValueError("three flat rules required")
        expression = rules[2][2].strip()
    elif "format: reflective-relay-v1" in spec_text:
        rules = re.findall(
            r"template\s+([^()\s]+)\(payload\):\s*\n\s*emit_source\(\"([^()\s]+)\((.+)\)\"\)",
            spec_text,
        )
        if len(rules) != 3:
            raise ValueError("three reflective rules required")
        expression = rules[2][2].strip()
    else:
        raise ValueError("unknown presentation")
    if expression == "payload":
        return "same"
    if expression == "flip(payload)":
        return "flip(payload)"
    return expression


def main() -> None:
    result = base_result(training_completed=True, model_saved=True, total_checks=TOTAL_CHECKS)
    result["scoreboard"] = "trajectory_solver_synthesis"
    patched_dir = validate_submission(result)
    require_changed_files(result, {"solution.py"})
    try:
        workdir, _ = make_workdir(patched_dir)
        sys.path.insert(0, workdir)
        import task
        from solution import solve

        checks = {}
        outputs = []
        for index, spec_text in enumerate(task.CASES):
            answer = solve(spec_text, "parse_only")
            expected = expected_parse(spec_text)
            outputs.append(answer)
            checks[f"case_{index}_exact"] = answer == expected
        checks["answer_types_are_strings"] = all(isinstance(value, str) for value in outputs)
        checks["witness_is_query_specific"] = (
            (outputs[0] == "same") if task.WITNESS_STATUS == "valid" else (outputs[0] != "same")
        )
        checks["format_only_does_not_change_answer"] = outputs[0] == outputs[1]
        passed = 0
        for name, value in checks.items():
            mark_check(result, name, bool(value))
            passed += int(bool(value))
        result["passed_checks"] = passed
        result["score"] = passed / TOTAL_CHECKS
        result["metrics"] = {"query_type": "parse_only", "track": "solver_synthesis_debugging"}
    except Exception as exc:
        set_failure(result, "runtime_error", str(exc))
        result["score"] = 0.0
    emit(result)


if __name__ == "__main__":
    main()
