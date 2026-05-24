#!/usr/bin/env python3
"""Judge for the BatchNorm EMA environment."""
import os
import sys
import torch

from judge_lib import (FAILURE_ARTIFACT_MISSING, FAILURE_REWARD_DENIAL, FAILURE_RUNTIME_ERROR,
                       FAILURE_TRAINING_FAILED, base_result, emit, eval_env, make_workdir,
                       prediction_coverage, prediction_entropy, run, score_from_accuracy,
                       scrub_workdir, set_failure, set_metric, train_env, validate_checkpoint,
                       validate_logits, validate_submission)

PASS_THRESHOLD = 0.75
PARTIAL_THRESHOLD = 0.50
JUDGE_SEED = int(os.environ.get("JUDGE_SEED", "0"))
SEED_OFFSET = 900719925474099
NUM_CLASSES = %%NUM_CLASSES%%


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
    workdir, original_files = make_workdir(patched_dir)
    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 1800, train_env(workdir))
    if tr.returncode != 0:
        set_failure(result, FAILURE_TRAINING_FAILED, "Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    checkpoint = os.path.join(workdir, "model.pth")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        set_failure(result, FAILURE_ARTIFACT_MISSING, str(exc))
        emit(result)
    result["model_saved"] = True
    scrub_workdir(workdir, original_files, {"model.pth"})
    labels = generate_evaluation_data(workdir)
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write("import sys, torch\n" + f"sys.path.insert(0, {workdir!r})\n" + "from model import load_model\nmodel = load_model('model.pth')\ninputs = torch.load('eval_inputs.pt', weights_only=True)\nwith torch.no_grad():\n    logits = model(inputs)\ntorch.save(logits, 'eval_outputs.pt')\n")
    ep = run([sys.executable, eval_script], workdir, 120, eval_env())
    if ep.returncode != 0:
        set_failure(result, FAILURE_RUNTIME_ERROR, "Evaluation failed:\n" + ep.stderr[-500:])
        emit(result)
    try:
        logits = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True, map_location="cpu")
        logits = validate_logits(logits, labels, NUM_CLASSES)
        preds = logits.argmax(1)
        accuracy = (preds == labels).float().mean().item()
        entropy = prediction_entropy(preds, NUM_CLASSES)
        coverage = prediction_coverage(preds)
        set_metric(result, "prediction_entropy", round(entropy, 6))
        set_metric(result, "predicted_classes", coverage)
        anti_gaming_passed = coverage >= min(NUM_CLASSES, 5) and entropy >= 1.0
    except Exception as exc:
        set_failure(result, FAILURE_REWARD_DENIAL, f"Failed to score outputs: {exc}")
        emit(result)
    score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=anti_gaming_passed)
    emit(result)


if __name__ == "__main__":
    main()
