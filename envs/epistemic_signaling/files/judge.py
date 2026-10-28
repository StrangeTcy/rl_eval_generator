#!/usr/bin/env python3
from __future__ import annotations
import ast, json, os, sys
from pathlib import Path
JUDGE_DIR = os.path.dirname(os.path.abspath(__file__))
if JUDGE_DIR not in sys.path:
    sys.path.insert(0, JUDGE_DIR)
import core, patch_validator, source_validator
from instance_spec import INSTANCE_SPEC
PATCH_PATH = os.environ.get("JUDGE_PATCH_PATH", "/submission/agent.patch")
PATCHABLE_FILES = %%PATCHABLE_FILES%%


def extract(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename="answer.py")
    assigns = [s for s in tree.body if isinstance(s, ast.Assign)]
    if len(assigns) != 1 or not isinstance(assigns[0].targets[0], ast.Name) or assigns[0].targets[0].id != "ANSWER":
        raise ValueError("one ANSWER assignment required")
    value = ast.literal_eval(assigns[0].value)
    if not isinstance(value, dict):
        raise ValueError("ANSWER must be a dict")
    return value


def main() -> None:
    result = {"score": 0.0, "failure_mode": "unknown", "metrics": {}}
    try:
        if set(PATCHABLE_FILES) != {"answer.py"} or not os.path.isfile(PATCH_PATH):
            raise ValueError("missing patch")
        patched = patch_validator.validate_patch()
        violations = source_validator.validate_directory(patched)
        if violations:
            raise ValueError("source validation failed")
        inst = core.build_instance(INSTANCE_SPEC["signal_type"], INSTANCE_SPEC["incentive"], INSTANCE_SPEC["scenario"], INSTANCE_SPEC["seed"])
        if inst.to_spec() != INSTANCE_SPEC:
            raise ValueError("instance provenance mismatch")
        grading = inst.grade(extract(Path(patched) / "answer.py"))
        result["score"] = 1.0 if grading["failure_mode"] == "pass" else grading["metrics"]["score"]
        result["failure_mode"] = grading["failure_mode"]
        result["metrics"] = grading["metrics"]
        result["checks"] = grading["checks"]
    except Exception as exc:
        result["failure_mode"] = "judge_or_answer_error"
        result["metrics"]["error"] = str(exc)
    result["verdict"] = "PASS" if result["score"] >= 1.0 else "FAIL"
    print(json.dumps(result))
    raise SystemExit(0 if result["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
