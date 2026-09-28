#!/usr/bin/env python3
"""Judge for the secondary complete-trajectory solver track."""
from __future__ import annotations

import re
import sys

from judge_lib import (
    base_result,
    emit,
    make_workdir,
    score_from_checks,
    require_changed_files,
    set_failure,
    validate_submission,
)

TOTAL_CHECKS = %%SCORING_TOTAL_CHECKS%%


def parse_spec(spec_text: str):
    payload_line = re.search(r"^payloads:\s*([^,]+),\s*(.+)$", spec_text, re.M)
    if not payload_line:
        raise ValueError("payload declaration missing")
    payload_labels = {payload_line.group(1).strip(): 0, payload_line.group(2).strip(): 1}
    if "format: flat-relay-v1" in spec_text:
        template_line = re.search(r"^templates:\s*(.+)$", spec_text, re.M)
        if not template_line:
            raise ValueError("template declaration missing")
        templates = tuple(item.strip() for item in template_line.group(1).split(","))
        rules = re.findall(
            r"^-\s+([^()\s]+)\(payload\)\s*->\s*([^()\s]+)\((.+)\)\s*$",
            spec_text,
            re.M,
        )
    elif "format: reflective-relay-v1" in spec_text:
        rules = re.findall(
            r"template\s+([^()\s]+)\(payload\):\s*\n\s*emit_source\(\"([^()\s]+)\((.+)\)\"\)",
            spec_text,
        )
        templates = tuple(rule[0] for rule in rules)
    else:
        raise ValueError("unknown format")
    if len(rules) != 3:
        raise ValueError("three rules required")
    transitions = {}
    for source, target, expression in rules:
        expression = expression.strip()
        if expression == "payload":
            operation = ("identity", None)
        elif expression == "flip(payload)":
            operation = ("flip", None)
        elif expression in payload_labels:
            operation = ("constant", payload_labels[expression])
        else:
            raise ValueError(f"unknown payload expression: {expression}")
        transitions[source] = (target, operation)
    return templates, transitions


def expected(spec_text: str, template: str, payload: int, horizon: int):
    templates, transitions = parse_spec(spec_text)
    if template not in templates or payload not in (0, 1):
        raise ValueError("initial state outside the system")
    state = (template, payload)
    for _ in range(horizon):
        source, current_payload = state
        target, (operation, constant) = transitions[source]
        if operation == "identity":
            next_payload = current_payload
        elif operation == "flip":
            next_payload = 1 - current_payload
        else:
            next_payload = constant
        state = (target, next_payload)
    return state


def check_case(solve, spec_text: str, horizons) -> bool:
    templates, _ = parse_spec(spec_text)
    return all(
        solve(spec_text, template, payload, horizon)
        == expected(spec_text, template, payload, horizon)
        for template in templates
        for payload in (0, 1)
        for horizon in horizons
    )


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

        checks = {
            "canonical_matched_horizons": check_case(solve, task.SPEC_TEXT, task.HORIZONS),
            "format_only_matched_horizons": check_case(solve, task.NOISY_SPEC_TEXT, task.HORIZONS),
            "relabeling_matched_horizons": check_case(solve, task.RELABELED_SPEC_TEXT, task.HORIZONS),
            "witness_sibling_matched_horizons": check_case(solve, task.SIBLING_SPEC_TEXT, task.HORIZONS),
            "witness_sibling_relabeling_matched_horizons": check_case(
                solve, task.SIBLING_RELABELED_SPEC_TEXT, task.HORIZONS
            ),
            "same_orbit_long_horizons": check_case(solve, task.SPEC_TEXT, (6, 30, 126, 510)),
            "zero_horizon_is_identity": all(
                solve(task.SPEC_TEXT, template, payload, 0) == (template, payload)
                for template in ("A", "B", "C")
                for payload in (0, 1)
            ),
        }
        score_from_checks(result, checks, TOTAL_CHECKS)
        result["metrics"] = {
            "query_type": "state_at_T",
            "matched_horizons": list(task.HORIZONS),
            "track": "solver_synthesis_debugging",
        }
    except Exception as exc:
        set_failure(result, "runtime_error", str(exc))
        result["score"] = 0.0
    emit(result)


if __name__ == "__main__":
    main()
