#!/usr/bin/env python3
"""Judge for tokenizer_adjunction environment."""
import os
import sys
import torch

from judge_lib import (base_result, emit, eval_env, judge_event, make_workdir,
                       mark_check, run, score_from_accuracy, scrub_workdir,
                       set_failure, set_metric, train_env, validate_submission,
                       require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%

def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"detokenizer.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys
sys.path.insert(0, {workdir!r})
from tokenizer import tokenize
from detokenizer import %%MODEL_CLASS%%

detok = %%MODEL_CLASS%%()

checks = {{}}

# 1. Output reconstruction correctness (no spaces)
try:
    text = "hello"
    tokens = tokenize(text)
    reconstructed = detok.detokenize(tokens)
    checks["basic_reconstruction"] = bool(reconstructed == text)
except Exception:
    checks["basic_reconstruction"] = False

# 2. Output spacing correctness
try:
    text = "hello world of category theory"
    tokens = tokenize(text)
    reconstructed = detok.detokenize(tokens)
    checks["spacing_correct"] = bool(reconstructed == text)
except Exception:
    checks["spacing_correct"] = False

# 3. Unit Adjunction Galois Connection (Strict CT Adjunction)
try:
    text_complex = "adjunctions are functors"
    tokens = tokenize(text_complex)
    
    # tokenize o detokenize o tokenize must equal tokenize
    m1 = tokenize(detok.detokenize(tokens))
    checks["adjunction_unit"] = bool(m1 == tokens)
except Exception:
    checks["adjunction_unit"] = False

# Save checks as dictionary
import torch
torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_reconstruction", False))
        space_ok = bool(checks.get("spacing_correct", False))
        adj_ok = bool(checks.get("adjunction_unit", False))

        mark_check(result, "basic_reconstruction", basic_ok)
        mark_check(result, "spacing_correct", space_ok)
        mark_check(result, "adjunction_unit", adj_ok)

        passed = sum([basic_ok, space_ok, adj_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
