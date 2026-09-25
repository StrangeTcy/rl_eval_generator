#!/usr/bin/env python3
"""Judge for the epistemic_games environment (torch-free, standard library only).

Scoring chain (the environment's structural diagnosis):

    instance -> latent game -> observations -> required inference -> verifiable answer

The judge never trusts the agent's narrative:

1. validates and applies the submission patch (shared patch_validator);
2. AST-validates the patched sources (shared source_validator);
3. re-derives the instance from (template, evidence, prior, presentation,
   seed) with core.py and requires the rebuilt specification to match the
   baked INSTANCE_SPEC exactly (provenance / anti-tamper check);
4. extracts ANSWER from answer.py as *data* (bounded literal, no code
   execution) — one ``ANSWER = <literal dict>`` assignment, parsed with
   ast.literal_eval, with size and AST-node limits;
5. grades the answer with core (calibration vs the true posterior, verdict
   band, direction, internal consistency) and emits a structured failure-mode
   diagnosis. Training reward (forgiving) is separated from strict correctness.

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

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
PATCHABLE_FILES = %%PATCHABLE_FILES%%

# Bounded parsing limits (P0 #2)
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
            "support_consistent": False,
            "posterior_within_tolerance": False,
            "posterior_within_strict_tolerance": False,
            "verdict_correct": False,
            "most_supported_correct": False,
            "all_correct": False,
        },
        "metrics": {},
        "notes": [],
        "events": [],
    }


def _safe_extract_answer(answer_path: Path) -> dict:
    """Extract ANSWER as data, no code execution.

    Allowed file shape:
    - optional docstring Expr nodes (Constant str)
    - exactly one Assign: ANSWER = <literal dict>
    - no imports, calls, attribute access, comprehensions, etc.
    - file size and AST node count bounded
    - value parsed with ast.literal_eval (no execution)
    """
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

    # Node-count bound
    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_AST_NODES:
        raise ValueError(f"answer.py AST too large: {node_count} nodes > {MAX_AST_NODES}")

    # Disallowed constructs — any occurrence is a rejection
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

    # Top-level shape: only Expr(docstring) and Assign allowed
    assigns = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr):
            # allow docstring (Constant str) only
            if not (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
                raise ValueError("answer.py may only contain a docstring and one ANSWER assignment")
        elif isinstance(stmt, ast.Assign):
            assigns.append(stmt)
        else:
            raise ValueError(f"answer.py contains disallowed statement: {type(stmt).__name__}")

    if len(assigns) != 1:
        raise ValueError(f"answer.py must contain exactly one ANSWER assignment, found {len(assigns)}")

    assign = assigns[0]
    # target must be exactly Name id=ANSWER
    if len(assign.targets) != 1:
        raise ValueError("ANSWER assignment must have single target")
    target = assign.targets[0]
    if not (isinstance(target, ast.Name) and target.id == "ANSWER"):
        raise ValueError("assignment target must be ANSWER")

    # Parse value as literal — no code execution
    try:
        value = ast.literal_eval(assign.value)
    except Exception as exc:
        raise ValueError(f"ANSWER is not a literal dict: {exc}") from exc

    if not isinstance(value, dict):
        raise ValueError(f"ANSWER must be a dict, got {type(value).__name__}")

    # JSON-size bound on the extracted dict
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
    changed = set()
    if not os.path.isfile(PATCH_PATH):
        return changed
    with open(PATCH_PATH, encoding="utf-8") as f:
        for line in f:
            if not (line.startswith("--- ") or line.startswith("+++ ")):
                continue
            path = line[4:].split("\t", 1)[0].strip()
            if path == "/dev/null":
                continue
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            changed.add(path)
    return changed


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
    result["verdict"] = "PASS" if result["score"] >= 1.0 else "FAIL"
    print(json.dumps(result))
    sys.exit(0 if result["verdict"] == "PASS" else 1)


def map_accuracy(accuracy: float, pass_threshold: float, partial_threshold: float) -> float:
    """Mirror of shared/judge_lib.score_from_accuracy's continuous mapping."""
    accuracy = float(accuracy)
    if accuracy >= pass_threshold:
        return 1.0
    if accuracy >= partial_threshold:
        denom = max(pass_threshold - partial_threshold, 1e-9)
        return 0.5 + 0.5 * min(1.0, max(0.0, (accuracy - partial_threshold) / denom))
    return 0.5 * min(1.0, max(0.0, accuracy / max(partial_threshold, 1e-9)))


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
            template=INSTANCE_SPEC["template"],
            evidence=INSTANCE_SPEC["evidence"],
            prior_id=INSTANCE_SPEC["prior_id"],
            presentation=INSTANCE_SPEC["presentation"],
            framing=INSTANCE_SPEC["framing"],
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
        f"template={INSTANCE_SPEC['template']} evidence={INSTANCE_SPEC['evidence']} "
        f"prior={INSTANCE_SPEC['prior_id']} presentation={INSTANCE_SPEC['presentation']} seed={INSTANCE_SPEC['seed']}",
    )
    result["metrics"]["instance"] = {
        "template": instance.template,
        "evidence": instance.evidence,
        "prior_id": instance.prior_id,
        "presentation": instance.presentation,
        "seed": instance.seed,
        "subfamily": instance.subfamily,
        "observation": instance.observation,
    }

    # 5. Answer extraction: bounded literal parsing, no execution.
    try:
        answer_payload = _safe_extract_answer(Path(patched_dir) / "answer.py")
    except Exception as exc:
        fail_early(result, "answer_format_invalid", f"answer.py extraction failed: {exc}")
    result["checks"]["answer_extracted"] = True
    result["answer_extracted"] = True
    judge_event(result, "answer_extracted", "ok", f"keys={sorted(answer_payload.keys())}")

    # 6. Grade (structured failure-mode diagnosis) and map to the final score.
    #    Training reward (epistemic_score, forgiving) is separated from strict
    #    correctness (all_correct requires verdict, support, consistency, and
    #    posterior within 0.02). Final score is 1.0 only on strict correctness.
    grading = instance.grade(answer_payload, pass_threshold=PASS_THRESHOLD)
    result["checks"].update({k: bool(v) for k, v in grading["checks"].items()})
    result["metrics"].update(grading["metrics"])
    result["notes"].extend(grading["notes"])
    epistemic_score = float(grading["metrics"]["score"])
    strict_correct = bool(grading["metrics"].get("strict_correct", False))
    result["raw_accuracy"] = epistemic_score
    result["metrics"]["strict_correct"] = strict_correct

    if strict_correct and grading["failure_mode"] == "pass":
        final_score = 1.0
    else:
        # forgiving training reward, but never pass without strict correctness
        final_score = map_accuracy(epistemic_score, PASS_THRESHOLD, PARTIAL_THRESHOLD)
        if final_score >= 1.0:
            final_score = 0.95  # cap: cannot pass without strict_correct

    if not required_ok:
        final_score = min(final_score, 0.95)

    result["score"] = round(final_score, 6)
    result["accuracy_bin"] = (
        "pass" if final_score >= 1.0 else ("partial" if final_score >= 0.5 else "fail")
    )

    if final_score >= 1.0:
        set_failure(result, "pass")
    else:
        set_failure(result, grading["failure_mode"])
    judge_event(
        result,
        "scored",
        "ok",
        f"epistemic_score={epistemic_score} strict={strict_correct} final_score={result['score']} mode={result['failure_mode']}",
    )
    emit(result)


if __name__ == "__main__":
    main()
