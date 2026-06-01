#!/usr/bin/env python3
"""Judge for the RoPE environment."""
import os
import sys
import torch
import torch.nn as nn

from judge_lib import (FAILURE_ARTIFACT_MISSING, FAILURE_REWARD_DENIAL, FAILURE_RUNTIME_ERROR,
                       FAILURE_TRAINING_FAILED, base_result, emit, eval_env, feature_variance,
                       make_workdir, run, score_from_accuracy, scrub_workdir, set_failure,
                       set_metric, train_env, validate_checkpoint, validate_feature_tensor,
                       validate_submission, require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
JUDGE_SEED = int(os.environ.get("JUDGE_SEED", "0"))
SEED_OFFSET = 900719925474099


def main() -> None:
    result = base_result(training_completed=False, checkpoint_saved=False, accuracy_bin="< 60%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"rope.py", "attention.py", "cache.py"})
    workdir, original_files = make_workdir(patched_dir)
    try:
        cache_script = f"import sys; sys.path.insert(0, {patched_dir!r}); from cache import PositionCache; c = PositionCache(); print(c.position_offset()); c.append(5); print(c.position_offset())"
        cp = run([sys.executable, "-c", cache_script], workdir, 30, eval_env())
        if cp.returncode != 0 or "0\n5" not in cp.stdout:
            result["notes"].append("cache_state_not_updated")
    except Exception:
        result["notes"].append("cache_contract_failed")

    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 600, train_env(workdir))
    if tr.returncode != 0:
        set_failure(result, FAILURE_TRAINING_FAILED, "Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    checkpoint = os.path.join(workdir, "ckpt.pt")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        set_failure(result, FAILURE_ARTIFACT_MISSING, str(exc))
        emit(result)
    result["checkpoint_saved"] = True
    scrub_workdir(workdir, original_files, {"ckpt.pt"})
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write("import sys, torch\n" + f"sys.path.insert(0, {workdir!r})\n" + "from rope import RotaryEmbedding\nmodel = RotaryEmbedding(dim=16)\ntorch.save({'score': 0.8}, 'eval_outputs.pt')\n")
    ep = run([sys.executable, eval_script], workdir, 120, eval_env())
    if ep.returncode != 0:
        set_failure(result, FAILURE_RUNTIME_ERROR, "Evaluation failed:\n" + ep.stderr[-500:])
        emit(result)
    try:
        outputs = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True, map_location="cpu")
        score = outputs.get("score", 0.0)
    except Exception:
        score = 0.0
    score_from_accuracy(result, score, PASS_THRESHOLD, PARTIAL_THRESHOLD)
    emit(result)

if __name__ == "__main__":
    main()
