#!/usr/bin/env python3
"""Judge for the secondary one-step solver track."""
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
    labels = (payload_line.group(1).strip(), payload_line.group(2).strip())
    payload_values = {labels[0]: 0, labels[1]: 1}
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
        elif expression in payload_values:
            operation = ("constant", payload_values[expression])
        else:
            raise ValueError(f"unknown payload expression: {expression}")
        transitions[source] = (target, operation)
    return templates, transitions


def expected(spec_text: str, template: str, payload: int):
    _, transitions = parse_spec(spec_text)
    target, (operation, constant) = transitions[template]
    if operation == "identity":
        next_payload = payload
    elif operation == "flip":
        next_payload = 1 - payload
    else:
        next_payload = constant
    return target, next_payload


def all_states(spec_text: str):
    templates, _ = parse_spec(spec_text)
    return [(template, payload) for template in templates for payload in (0, 1)]


def check_case(solve, spec_text: str) -> bool:
    return all(
        solve(spec_text, template, payload) == expected(spec_text, template, payload)
        for template, payload in all_states(spec_text)
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
            "canonical_all_states": check_case(solve, task.SPEC_TEXT),
            "format_only_all_states": check_case(solve, task.NOISY_SPEC_TEXT),
            "relabeling_all_states": check_case(solve, task.RELABELED_SPEC_TEXT),
            "witness_sibling_all_states": check_case(solve, task.SIBLING_SPEC_TEXT),
            "witness_sibling_relabeling_all_states": check_case(
                solve, task.SIBLING_RELABELED_SPEC_TEXT
            ),
            "same_result_under_format_noise": check_case(solve, task.SPEC_TEXT)
            == check_case(solve, task.NOISY_SPEC_TEXT),
            "returns_state_tuples": all(
                isinstance(solve(task.SPEC_TEXT, template, payload), tuple)
                and len(solve(task.SPEC_TEXT, template, payload)) == 2
                for template, payload in all_states(task.SPEC_TEXT)
            ),
        }
        score_from_checks(result, checks, TOTAL_CHECKS)
        result["metrics"] = {"query_type": "one_step", "track": "solver_synthesis_debugging"}
    except Exception as exc:
        set_failure(result, "runtime_error", str(exc))
        result["score"] = 0.0
    emit(result)


if __name__ == "__main__":
    main()
