#!/usr/bin/env python3
"""Judge for the BatchNorm EMA environment."""
import os
import sys
import torch

from judge_lib import (FAILURE_ARTIFACT_MISSING, FAILURE_REWARD_DENIAL, FAILURE_RUNTIME_ERROR,
                       FAILURE_TRAINING_FAILED, base_result, emit, eval_env, judge_event, make_workdir,
                       mark_check, prediction_coverage, prediction_entropy, run, score_from_accuracy,
                       scrub_workdir, set_failure, set_metric, train_env, validate_checkpoint,
                       validate_logits, validate_submission, require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
JUDGE_SEED = int(os.environ.get("JUDGE_SEED", "0"))
SEED_OFFSET = 900719925474099
NUM_CLASSES = %%NUM_CLASSES%%

# Behavioral probe: produce held-out logits AND inspect normalization health.
# The checks are route-agnostic so any valid fix (momentum scaling, frozen-stat
# accumulation, post-hoc recalibration, or swapping BatchNorm for GroupNorm/
# LayerNorm) is accepted. They detect corrupted running statistics and
# train/eval inconsistency rather than any particular code shape.
EVAL_PROBE = '''
import sys, torch
import torch.nn as nn
sys.path.insert(0, {workdir!r})
from model import load_model

model = load_model("model.pth")
model.eval()
inputs = torch.load("eval_inputs.pt", weights_only=True)

bn_modules = [m for m in model.modules() if isinstance(m, nn.modules.batchnorm._BatchNorm)]
has_bn = len(bn_modules) > 0
bn_stats_ok = True
for m in bn_modules:
    rv, rm = m.running_var, m.running_mean
    if rv is None or rm is None:
        continue
    if not (torch.isfinite(rv).all() and torch.isfinite(rm).all()):
        bn_stats_ok = False
    # Degenerate running variance (collapsed to ~0 or exploded) indicates the
    # statistics were corrupted during accumulation.
    if float(rv.min()) <= 1e-6 or float(rv.max()) > 1e6:
        bn_stats_ok = False

with torch.no_grad():
    # Batch the forward pass; a single 2000-image batch is slow and memory-heavy.
    batches = [model(inputs[i:i + 128]) for i in range(0, inputs.shape[0], 128)]
    logits = torch.cat(batches, dim=0)
    # Eval mode must be deterministic across identical passes. Re-run only a
    # small slice to keep the probe cheap.
    probe_slice = inputs[:64]
    c1 = model(probe_slice)
    c2 = model(probe_slice)
eval_consistent = bool(torch.allclose(c1, c2, atol=1e-4))

torch.save({{"logits": logits, "has_bn": has_bn, "bn_stats_ok": bool(bn_stats_ok),
            "eval_consistent": eval_consistent}}, "eval_outputs.pt")
'''


def generate_evaluation_data(workdir: str):
    num_samples = 2000
    gen = torch.Generator().manual_seed(JUDGE_SEED + SEED_OFFSET)
    labels = torch.randint(0, NUM_CLASSES, (num_samples,), generator=gen)
    data = torch.zeros(num_samples, 3, 32, 32)
    for i, label in enumerate(labels.tolist()):
        row = (label * 7) % 24
        col = (label * 11) % 24
        channel = label % 3
        data[i, channel, row:row + 8, col:col + 8] = 1.0
        data[i, (channel + 1) % 3, 4:12, (label * 3) % 24:(label * 3) % 24 + 8] = 0.5
    data += torch.randn(data.shape, generator=gen) * 0.08
    data = data.clamp(0.0, 1.0)
    data = (data - 0.5) / 0.5
    torch.save(data, os.path.join(workdir, "eval_inputs.pt"))
    return labels


def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="< 50%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"model.py", "train.py"})
    workdir, original_files = make_workdir(patched_dir)
    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 1800, train_env(workdir))
    if tr.returncode != 0:
        set_failure(result, FAILURE_TRAINING_FAILED, "Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    mark_check(result, "training_completed")
    judge_event(result, "train", "ok", "training script completed")
    checkpoint = os.path.join(workdir, "model.pth")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        set_failure(result, FAILURE_ARTIFACT_MISSING, str(exc))
        emit(result)
    result["model_saved"] = True
    mark_check(result, "artifact_found")
    scrub_workdir(workdir, original_files, {"model.pth"})
    labels = generate_evaluation_data(workdir)
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(EVAL_PROBE.format(workdir=workdir))
    ep = run([sys.executable, eval_script], workdir, 300, eval_env())
    if ep.returncode != 0:
        detail = (ep.stderr or ep.stdout or "").strip()[-500:] or "(no output; the probe may have timed out)"
        set_failure(result, FAILURE_RUNTIME_ERROR, "Evaluation failed:\n" + detail)
        emit(result)
    try:
        outputs = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True, map_location="cpu")
        if not isinstance(outputs, dict) or "logits" not in outputs:
            raise RuntimeError("probe did not produce a logits dict")
        logits = validate_logits(outputs.get("logits"), labels, NUM_CLASSES)
        preds = logits.argmax(1)
        accuracy = (preds == labels).float().mean().item()
        entropy = prediction_entropy(preds, NUM_CLASSES)
        coverage = prediction_coverage(preds)
        set_metric(result, "prediction_entropy", round(entropy, 6))
        set_metric(result, "predicted_classes", coverage)
        anti_gaming_passed = coverage >= min(NUM_CLASSES, 5) and entropy >= 1.0

        # --- behavioral checks: attribute the failure cause ---------------
        has_bn = bool(outputs.get("has_bn", False))
        bn_stats_ok = bool(outputs.get("bn_stats_ok", True))
        eval_consistent = bool(outputs.get("eval_consistent", True))
        set_metric(result, "uses_batchnorm", has_bn)

        # Running statistics corrupted by accumulation (only meaningful if the
        # solution kept BatchNorm; a GroupNorm/LayerNorm swap has no BN buffers).
        running_stats_ok = (not has_bn) or bn_stats_ok
        mark_check(result, "running_stats_sane", running_stats_ok)
        judge_event(result, "check", "ok" if running_stats_ok else "fail", "running_stats_sane")
        if has_bn and not bn_stats_ok:
            result["notes"].append("bn_momentum_unscaled")

        # Eval-mode statistics must be stable across identical passes.
        mark_check(result, "eval_mode_consistent", eval_consistent)
        judge_event(result, "check", "ok" if eval_consistent else "fail", "eval_mode_consistent")
        if not eval_consistent:
            result["notes"].append("eval_mode_stats_bad")
    except Exception as exc:
        set_failure(result, FAILURE_REWARD_DENIAL, f"Failed to score outputs: {exc}")
        emit(result)
    score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=anti_gaming_passed)
    emit(result)


if __name__ == "__main__":
    main()
