#!/usr/bin/env python3
"""Torch-free direct-answer judge for the epistemic_reasoning family.

The judge validates the patch, re-derives the seed-rendered instance, parses
ANSWER strictly as data (never executes the learner file), and scores the exact
variant-specific contract with check-fraction semantics.
"""

from __future__ import annotations

import ast
import json
import os
import time
from pathlib import Path
from typing import Any

import patch_validator
import source_validator
import task_engine
from instance_spec import INSTANCE_SPEC

PATCH_PATH = os.environ.get("JUDGE_PATCH_PATH", "/submission/agent.patch")
ORIGINALS_DIR = os.environ.get("JUDGE_ORIGINALS_DIR", "/originals")
PATCHABLE_FILES = %%PATCHABLE_FILES%%
TOTAL_CHECKS = %%SCORING_TOTAL_CHECKS%%
MAX_ANSWER_FILE_BYTES = 20_000
MAX_ANSWER_AST_NODES = 500
MAX_ANSWER_JSON_BYTES = 10_000


def base_result() -> dict[str, Any]:
    return {
        "score": 0.0,
        "raw_accuracy": 0.0,
        "failure_mode": "unknown",
        "checks": {
            "patch_found": False,
            "patch_valid": False,
            "sources_valid": False,
            "provenance_ok": False,
            "answer_schema_valid": False,
            "answer_exactly_correct": False,
        },
        "metrics": {},
        "notes": [],
        "events": [],
    }


def judge_event(result: dict[str, Any], action: str, status: str = "ok", summary: str = "") -> None:
    result["events"].append(
        {
            "ts": round(time.time(), 3),
            "tool": "judge",
            "action": action,
            "status": status,
            "summary": summary,
        }
    )


def set_failure(result: dict[str, Any], mode: str, note: str = "") -> None:
    result["failure_mode"] = mode
    if note:
        result["notes"].append(note)


def emit(result: dict[str, Any]) -> None:
    if result.get("failure_mode") in (None, "unknown"):
        result["score"] = 0.0
        set_failure(result, "judge_runtime_error", "Judge emitted without a classified result")
    result["verdict"] = "PASS" if result.get("score", 0.0) >= 1.0 else "FAIL"
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["verdict"] == "PASS" else 1)


def fail_early(result: dict[str, Any], mode: str, note: str) -> None:
    set_failure(result, mode, note)
    judge_event(result, mode, "fail", note)
    emit(result)


def require_changed_files(result: dict[str, Any], required: set[str]) -> bool:
    """Record required target edits using the target runner's standard contract."""
    if not os.path.isfile(PATCH_PATH):
        changed: set[str] = set()
    else:
        with open(PATCH_PATH, encoding="utf-8") as handle:
            changed = patch_validator.modified_files_from_patch(handle.read())
    missing = sorted(set(required) - changed)
    result["metrics"]["changed_files"] = sorted(changed)
    result["metrics"]["missing_required_files"] = missing
    if missing:
        result["notes"].append("Submission did not change required file(s): " + ", ".join(missing))
    return not missing


def _safe_extract_answer(path: Path) -> dict[str, Any]:
    """Parse a single literal ANSWER assignment without executing submitted code."""
    if not path.is_file():
        raise ValueError("answer.py is missing")
    raw = path.read_bytes()
    if len(raw) > MAX_ANSWER_FILE_BYTES:
        raise ValueError("answer.py exceeds the byte limit")
    text = raw.decode("utf-8", errors="strict")
    tree = ast.parse(text, filename="answer.py")
    if sum(1 for _ in ast.walk(tree)) > MAX_ANSWER_AST_NODES:
        raise ValueError("answer.py exceeds the AST node limit")

    assignments = []
    for statement in tree.body:
        if isinstance(statement, ast.Expr):
            if not (
                isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)
            ):
                raise ValueError("answer.py may contain only a docstring and ANSWER assignment")
        elif isinstance(statement, ast.Assign):
            assignments.append(statement)
        else:
            raise ValueError(f"answer.py contains disallowed statement {type(statement).__name__}")
    if len(assignments) != 1 or len(assignments[0].targets) != 1:
        raise ValueError("answer.py must contain exactly one assignment to ANSWER")
    target = assignments[0].targets[0]
    if not isinstance(target, ast.Name) or target.id != "ANSWER":
        raise ValueError("the assignment target must be ANSWER")
    answer = ast.literal_eval(assignments[0].value)
    if type(answer) is not dict:
        raise ValueError("ANSWER must be a literal dictionary")
    encoded = json.dumps(answer, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_ANSWER_JSON_BYTES:
        raise ValueError("ANSWER exceeds the JSON size limit")
    return answer


def score_from_checks(
    result: dict[str, Any], checks: dict[str, bool], total_checks: int, required_ok: bool
) -> None:
    """Torch-free equivalent of shared.judge_lib.score_from_checks for this judge."""
    if total_checks < 1 or len(checks) != total_checks:
        set_failure(
            result, "judge_runtime_error", f"expected {total_checks} checks, got {len(checks)}"
        )
        return
    passed = 0
    for name, value in checks.items():
        result["checks"][name] = bool(value)
        passed += int(bool(value))
    accuracy = passed / total_checks
    result["passed_checks"] = passed
    result["raw_accuracy"] = accuracy
    result["metrics"]["trusted_score"] = round(accuracy, 6)
    result["checks"]["hidden_metric_passed"] = passed == total_checks
    result["checks"]["anti_gaming_passed"] = required_ok
    result["score"] = min(accuracy, 0.95) if not required_ok else accuracy
    if passed == total_checks and required_ok:
        set_failure(result, "pass")
    elif not required_ok:
        set_failure(result, "overfit_visible_tests")
    else:
        set_failure(result, "underfit")


def _rederive_instance() -> dict[str, Any]:
    if type(INSTANCE_SPEC) is not dict:
        raise ValueError("baked instance specification is not a dictionary")
    if set(INSTANCE_SPEC) != {
        "schema_version",
        "variant",
        "size",
        "seed",
        "public",
        "expected_answer",
    }:
        raise ValueError("baked instance specification has an unexpected schema")
    rebuilt = task_engine.build_instance(
        INSTANCE_SPEC["variant"], INSTANCE_SPEC["size"], INSTANCE_SPEC["seed"]
    )
    if rebuilt != INSTANCE_SPEC:
        raise ValueError("seed-derived instance does not match baked oracle specification")
    return rebuilt


def main() -> None:
    result = base_result()
    judge_event(result, "judge_start")
    if set(PATCHABLE_FILES) != {"answer.py"}:
        fail_early(result, "reward_denial", "PATCHABLE_FILES must be exactly ['answer.py']")
    if not os.path.isfile(PATCH_PATH):
        fail_early(result, "patch_missing", f"No patch found at {PATCH_PATH}")
    result["checks"]["patch_found"] = True

    try:
        patched_dir = patch_validator.validate_patch()
    except Exception as exc:
        fail_early(result, "patch_invalid", f"Patch validation failed: {exc}")
    result["checks"]["patch_valid"] = True
    judge_event(result, "patch_valid", "ok", f"patched directory: {patched_dir}")

    violations = source_validator.validate_directory(patched_dir)
    if violations:
        fail_early(result, "source_invalid", "Source validation failed: " + "; ".join(violations))
    result["checks"]["sources_valid"] = True
    judge_event(result, "sources_valid")

    # Keep this exact call shape discoverable by env_runner's required-file parser.
    required_ok = require_changed_files(result, {"answer.py"})

    try:
        instance = _rederive_instance()
    except Exception as exc:
        fail_early(result, "reward_denial", f"Instance provenance check failed: {exc}")
    result["checks"]["provenance_ok"] = True
    public = instance["public"]
    variant = instance["variant"]
    expected = instance["expected_answer"]
    result["metrics"].update(
        {
            "variant": variant,
            "size": instance["size"],
            "seed": instance["seed"],
            "oracle_answer": expected,
        }
    )
    judge_event(result, "provenance_ok", "ok", f"variant={variant} seed={instance['seed']}")

    try:
        answer = _safe_extract_answer(Path(patched_dir) / "answer.py")
        errors = task_engine.validate_answer(variant, answer, public)
    except Exception as exc:
        answer = None
        errors = [str(exc)]
    schema_valid = not errors
    if errors:
        result["notes"].extend(errors)
    exact_correct = schema_valid and task_engine.answers_equal(variant, answer, expected, public)
    checks = {
        "answer_schema_valid": schema_valid,
        "answer_exactly_correct": exact_correct,
    }
    result["checks"]["answer_schema_valid"] = schema_valid
    result["checks"]["answer_exactly_correct"] = exact_correct
    judge_event(
        result,
        "answer_graded",
        "ok" if exact_correct else "fail",
        f"schema_valid={schema_valid}; exact_correct={exact_correct}",
    )
    score_from_checks(result, checks, TOTAL_CHECKS, required_ok)
    emit(result)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        result = base_result()
        set_failure(result, "judge_runtime_error", f"Unhandled judge error: {exc}")
        emit(result)
