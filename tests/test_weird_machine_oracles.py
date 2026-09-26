"""Behavioural oracle/no-op/wrong/transcription validation for weird_machine judges.

Each judge is exercised through the exact-instance gate on the *generated*
instance (never on template sources): the reference must PASS, the no-op must
fail closed as an invalid patch, a plausible-but-wrong patch must FAIL the
named randomized check, and a "transcription" patch that hard-codes the exact
outputs asserted by visible_tests.py must also FAIL. If a judge cannot reject
the transcription, the visible-output hard-coding prediction cannot be tested.
"""
from __future__ import annotations

import pytest

from tools import instance_oracle_gate as gate

WEIRD_ENVS = [
    "ci_dependency_graph",
    "css_state_machine",
    "regex_state_machine",
    "spreadsheet_dataflow",
    "sql_fixed_point",
    "template_interpreter",
]

# Judge checks a transcription still satisfies, proving the submission is a
# working hard-code of the visible tests rather than a broken patch. The CI
# dependency judge's fixed checks all use different DAGs than the visible test,
# so only the randomized check can reject its transcription.
VISIBLE_MECHANISM_CHECKS: dict[str, tuple[str, ...]] = {
    "regex_state_machine": ("regex_used",),
    "sql_fixed_point": ("query_is_sql",),
    "css_state_machine": ("rule_structure",),
    "spreadsheet_dataflow": ("formula_syntax",),
    "template_interpreter": ("template_syntax",),
}


def _validate_quadruple(environment: str, difficulty: str, seed: int) -> dict:
    pytest.importorskip("torch")
    if environment == "template_interpreter":
        pytest.importorskip("jinja2")
    row = gate.validate_case({
        "case_id": f"wm-{environment}", "environment": environment,
        "difficulty": difficulty, "seed": seed,
    })
    assert row["status"] == "passed", row
    assert [v["variant"] for v in row["variants"]] == [
        "no_op", "plausible_wrong", "transcription", "reference",
    ]
    no_op, wrong, transcription, reference = row["variants"]
    negative_check = gate.REFERENCES[environment][1]

    assert no_op["score"] == 0 and no_op["failure_mode"] == "patch_invalid"

    assert wrong["verdict"] == "FAIL" and wrong["score"] < 1
    assert wrong["checks"]["patch_valid"] is True
    assert wrong["checks"][negative_check] is False

    assert transcription["verdict"] == "FAIL" and transcription["score"] < 1
    assert transcription["checks"]["patch_valid"] is True
    assert transcription["checks"][negative_check] is False
    for check in VISIBLE_MECHANISM_CHECKS.get(environment, ()):
        assert transcription["checks"][check] is True, (
            f"{environment}: transcription is not a working hard-code of the "
            f"visible tests (check {check} unexpectedly False)"
        )

    assert reference["verdict"] == "PASS" and reference["score"] == 1
    assert all(v["accepted"] for v in row["variants"])
    return row


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("environment", WEIRD_ENVS)
def test_weird_machine_judge_quadruple_at_easy_vector(environment: str, seed: int):
    _validate_quadruple(environment, "easy,easy", seed)


@pytest.mark.parametrize("environment", WEIRD_ENVS)
def test_weird_machine_judge_quadruple_at_hard_vector(environment: str):
    _validate_quadruple(environment, "hard,hard", 0)
