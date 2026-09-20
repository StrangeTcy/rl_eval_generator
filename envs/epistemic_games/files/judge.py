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
4. executes the agent's answer.py in an isolated subprocess to extract
   ANSWER as JSON (agent code can influence only the answer, nothing else);
5. grades the answer with core (calibration vs the true posterior, verdict
   band, direction) and emits a structured failure-mode diagnosis.
"""
import json
import os
import subprocess
import sys
import time

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

ANSWER_EXTRACT_SNIPPET = "import json, answer; print(json.dumps(answer.ANSWER))"


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
            "posterior_within_tolerance": False,
            "verdict_correct": False,
            "most_supported_correct": False,
        },
        "metrics": {},
        "notes": [],
        "events": [],
    }


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

    # 5. Answer extraction: execute the agent's answer.py in isolation.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-c", ANSWER_EXTRACT_SNIPPET],
        cwd=patched_dir,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    answer_payload = None
    if proc.returncode != 0:
        fail_early(result, "answer_format_invalid", f"answer.py failed to execute: {proc.stderr[-800:]}")
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if lines:
        try:
            answer_payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            fail_early(result, "answer_format_invalid", f"ANSWER is not valid JSON: {exc}")
    else:
        fail_early(result, "answer_format_invalid", "answer.py printed no answer")
    result["checks"]["answer_extracted"] = True
    result["answer_extracted"] = True
    judge_event(result, "answer_extracted", "ok")

    # 6. Grade (structured failure-mode diagnosis) and map to the final score.
    grading = instance.grade(answer_payload, pass_threshold=PASS_THRESHOLD)
    result["checks"].update({k: bool(v) for k, v in grading["checks"].items()})
    result["metrics"].update(grading["metrics"])
    result["notes"].extend(grading["notes"])
    epistemic_score = float(grading["metrics"]["score"])
    result["raw_accuracy"] = epistemic_score
    final_score = map_accuracy(epistemic_score, PASS_THRESHOLD, PARTIAL_THRESHOLD)
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
    judge_event(result, "scored", "ok", f"epistemic_score={epistemic_score} final_score={result['score']}")
    emit(result)


if __name__ == "__main__":
    main()
