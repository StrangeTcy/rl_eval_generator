#!/usr/bin/env python3
"""Judge for the epistemic_nested_knowledge environment (torch-free, stdlib only).

Scoring chain:

    instance -> S5 model -> registered nested query -> exact truth

The judge never trusts the agent's narrative:

1. validates and applies the submission patch (shared patch_validator);
2. AST-validates the patched sources (shared source_validator);
3. re-derives the instance from (worlds, order, scenario, seed) with
   core.py and requires the rebuilt specification to match the baked
   INSTANCE_SPEC exactly (provenance / anti-tamper check);
4. extracts ANSWER from answer.py as *data* (bounded literal, no code
   execution) — one ``ANSWER = <literal dict>`` assignment, parsed with
   ast.literal_eval, with size and AST-node limits;
5. grades exact truth classification (full credit only on the exact truth
   value of the registered query in the final restricted model).

Security note: the shared source_validator is explicitly not a sandbox.
This judge does NOT import or execute answer.py; it parses it as data.
"""

import ast
import json
import os
import sys
import time
from pathlib import Path

JUDGE_DIR = os.path.dirname(os.path.abspath(__file__))
if JUDGE_DIR not in sys.path:
    sys.path.insert(0, JUDGE_DIR)

import core
import patch_validator
import source_validator
from instance_spec import INSTANCE_SPEC

PATCH_PATH = os.environ.get("JUDGE_PATCH_PATH", "/submission/agent.patch")
ORIGINALS_DIR = os.environ.get("JUDGE_ORIGINALS_DIR", "/originals")

PATCHABLE_FILES = %%PATCHABLE_FILES%%

# Bounded parsing limits
MAX_ANSWER_FILE_BYTES = 20_000
MAX_AST_NODES = 500
MAX_ANSWER_JSON_BYTES = 5_000


def base_result() -> dict:
    return {
        "score": 0.0,
        "raw_accuracy": 0.0,
        "failure_mode": "unknown",
        "checks": {
            "patch_found": False,
            "patch_valid": False,
            "sources_valid": False,
            "provenance_ok": False,
            "answer_extracted": False,
            "answer_format_valid": False,
            "truth_correct": False,
            "all_correct": False,
        },
        "metrics": {},
        "notes": [],
        "events": [],
    }


def _safe_extract_answer(answer_path: Path) -> dict:
    """Extract ANSWER as data, no code execution."""
    if not answer_path.is_file():
        raise ValueError(f"answer.py not found at {answer_path}")
    size = answer_path.stat().st_size
    if size > MAX_ANSWER_FILE_BYTES:
        raise ValueError(f"answer.py too large: {size} bytes > {MAX_ANSWER_FILE_BYTES}")
    text = answer_path.read_text(encoding="utf-8", errors="strict")
    if len(text.encode("utf-8")) > MAX_ANSWER_FILE_BYTES:
        raise ValueError("answer.py exceeds byte limit")

    try:
        tree = ast.parse(text, filename="answer.py")
    except SyntaxError as exc:
        raise ValueError(f"answer.py syntax error: {exc}") from exc

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_AST_NODES:
        raise ValueError(f"answer.py AST too large: {node_count} nodes > {MAX_AST_NODES}")

    disallowed = (
        ast.Import,
        ast.ImportFrom,
        ast.Call,
        ast.Attribute,
        ast.Subscript,
        ast.ListComp,
        ast.DictComp,
        ast.SetComp,
        ast.GeneratorExp,
        ast.Lambda,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.If,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        ast.Raise,
        ast.Delete,
        ast.Global,
        ast.Nonlocal,
        ast.Await,
        ast.Yield,
        ast.YieldFrom,
        ast.NamedExpr,
    )
    for node in ast.walk(tree):
        if isinstance(node, disallowed):
            raise ValueError(f"answer.py contains disallowed construct: {type(node).__name__}")

    assigns = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr):
            if not (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
                raise ValueError("answer.py may only contain a docstring and one ANSWER assignment")
        elif isinstance(stmt, ast.Assign):
            assigns.append(stmt)
        else:
            raise ValueError(f"answer.py contains disallowed statement: {type(stmt).__name__}")

    if len(assigns) != 1:
        raise ValueError(f"answer.py must contain exactly one ANSWER assignment, found {len(assigns)}")

    assign = assigns[0]
    if len(assign.targets) != 1:
        raise ValueError("ANSWER assignment must have single target")
    target = assign.targets[0]
    if not (isinstance(target, ast.Name) and target.id == "ANSWER"):
        raise ValueError("assignment target must be ANSWER")

    try:
        value = ast.literal_eval(assign.value)
    except Exception as exc:
        raise ValueError(f"ANSWER is not a literal dict: {exc}") from exc

    if not isinstance(value, dict):
        raise ValueError(f"ANSWER must be a dict, got {type(value).__name__}")

    try:
        json_bytes = json.dumps(value).encode("utf-8")
    except Exception as exc:
        raise ValueError(f"ANSWER not JSON-serializable: {exc}") from exc
    if len(json_bytes) > MAX_ANSWER_JSON_BYTES:
        raise ValueError(f"ANSWER JSON too large: {len(json_bytes)} > {MAX_ANSWER_JSON_BYTES}")

    return value


def judge_event(result: dict, action: str, status: str = "ok", summary: str = "") -> None:
    result["events"].append(
        {"ts": round(time.time(), 3), "tool": "judge", "action": action, "status": status, "summary": summary}
    )


def set_failure(result: dict, mode: str, note: str = "") -> None:
    result["failure_mode"] = mode
    if note:
        result["notes"].append(note)


def changed_files_from_patch() -> set:
    if not os.path.isfile(PATCH_PATH):
        return set()
    with open(PATCH_PATH, encoding="utf-8") as f:
        return patch_validator.modified_files_from_patch(f.read())


def require_changed_files(result: dict, required) -> bool:
    """Record whether the submission touches every required file (non-terminal)."""
    required_set = set(required)
    changed = changed_files_from_patch()
    result["metrics"]["changed_files"] = sorted(changed)
    missing = sorted(required_set - changed)
    result["metrics"]["missing_required_files"] = missing
    ok = not missing
    if missing:
        result["notes"].append("Submission does not touch all required files; missing: " + ", ".join(missing))
    return ok


def emit(result: dict) -> None:
    if result.get("failure_mode") in (None, "unknown"):
        result["score"] = 0.0
        set_failure(result, "judge_runtime_error", "Judge emitted a verdict without a failure mode")
    result["verdict"] = "PASS" if result["score"] >= 1.0 else "FAIL"
    print(json.dumps(result))
    sys.exit(0 if result["verdict"] == "PASS" else 1)


def fail_early(result: dict, mode: str, note: str) -> None:
    set_failure(result, mode, note)
    judge_event(result, mode, "fail", note)
    emit(result)


def main() -> None:
    result = base_result()
    judge_event(result, "judge_start")

    # Config/judge sync guard (the runner parses the literal set, see below).
    if set(PATCHABLE_FILES) != {"answer.py"}:
        fail_early(
            result,
            "reward_denial",
            "config PATCHABLE_FILES out of sync with the judge required-file literal: "
            f"{sorted(PATCHABLE_FILES)}",
        )

    # 1. Patch validation (shared protocol).
    if not os.path.isfile(PATCH_PATH):
        fail_early(result, "patch_missing", f"No patch found at {PATCH_PATH}")
    result["checks"]["patch_found"] = True
    result["patch_found"] = True
    try:
        patched_dir = patch_validator.validate_patch()
    except RuntimeError as exc:
        result.setdefault("stage_outcomes", {})["patch_validation"] = {
            "status": "failed",
            "code": getattr(exc, "code", "patch_invalid"),
        }
        fail_early(result, "patch_invalid", f"Patch validation failed: {exc}")
    result["checks"]["patch_valid"] = True
    result["patch_valid"] = True
    judge_event(result, "patch_valid", "ok", f"patched dir: {patched_dir}")

    # 2. Source validation (shared protocol).
    violations = source_validator.validate_directory(patched_dir)
    if violations:
        fail_early(result, "source_invalid", "Source validation failed:\n" + "\n".join(violations))
    result["checks"]["sources_valid"] = True
    result["sources_valid"] = True
    judge_event(result, "sources_valid", "ok")

    # 3. Required-file check (non-terminal, matches the env_runner contract).
    # NOTE: the literal set below is what env_runner.py parses to know which
    # files the submission must touch; keep it in sync with the config's
    # %%PATCHABLE_FILES%% constant (["answer.py"]).
    required_ok = require_changed_files(result, {"answer.py"})

    # 4. Provenance: re-derive the instance and require an exact match with
    #    the baked specification.
    try:
        instance = core.build_instance(
            worlds=INSTANCE_SPEC["worlds"],
            order=INSTANCE_SPEC["order"],
            scenario=INSTANCE_SPEC["scenario"],
            seed=INSTANCE_SPEC["seed"],
        )
        rebuilt = instance.to_spec()
    except Exception as exc:
        fail_early(result, "reward_denial", f"Instance re-derivation failed: {exc}")
    if rebuilt != INSTANCE_SPEC:
        diff_keys = sorted(k for k in set(rebuilt) | set(INSTANCE_SPEC) if rebuilt.get(k) != INSTANCE_SPEC.get(k))
        fail_early(
            result,
            "reward_denial",
            "Instance provenance mismatch: rebuilt spec differs from baked spec in: " + ", ".join(diff_keys),
        )
    result["checks"]["provenance_ok"] = True
    result["provenance_ok"] = True
    judge_event(
        result,
        "provenance_ok",
        "ok",
        f"worlds={INSTANCE_SPEC['worlds']} order={INSTANCE_SPEC['order']} "
        f"scenario={INSTANCE_SPEC['scenario']} seed={INSTANCE_SPEC['seed']}",
    )
    result["metrics"]["instance"] = {
        "worlds": instance.worlds_axis,
        "order": instance.order_axis,
        "scenario": instance.scenario,
        "seed": instance.seed,
        "query_order": instance.to_spec()["query_order"],
    }

    # 5. Answer extraction: bounded literal parsing, no execution.
    try:
        answer_payload = _safe_extract_answer(Path(patched_dir) / "answer.py")
    except Exception as exc:
        fail_early(result, "answer_format_invalid", f"answer.py extraction failed: {exc}")
    result["checks"]["answer_extracted"] = True
    result["answer_extracted"] = True
    judge_event(result, "answer_extracted", "ok", f"keys={sorted(answer_payload.keys())}")

    # 6. Grade: exact truth classification. Full credit only on the exact
    #    truth value; there is no partial credit for a half-right
    #    classification of a registered proposition.
    grading = instance.grade(answer_payload, pass_threshold=1.0)
    result["checks"].update({k: bool(v) for k, v in grading["checks"].items()})
    result["metrics"].update(grading["metrics"])
    result["notes"].extend(grading["notes"])
    result["checks"]["all_correct"] = grading["checks"]["truth_correct"]
    accuracy = float(grading["metrics"]["score"])
    strict_correct = bool(grading["metrics"].get("strict_correct", False))
    result["raw_accuracy"] = accuracy
    result["metrics"]["strict_correct"] = strict_correct

    final_score = 1.0 if (strict_correct and grading["failure_mode"] == "pass") else 0.0
    if not required_ok:
        final_score = min(final_score, 0.95)

    result["score"] = round(final_score, 6)
    result["accuracy_bin"] = "pass" if final_score >= 1.0 else "fail"

    if final_score >= 1.0:
        set_failure(result, "pass")
    else:
        set_failure(result, grading["failure_mode"])
    judge_event(
        result,
        "scored",
        "ok",
        f"accuracy={accuracy} strict={strict_correct} final_score={result['score']} mode={result['failure_mode']}",
    )
    emit(result)


if __name__ == "__main__":
    main()
