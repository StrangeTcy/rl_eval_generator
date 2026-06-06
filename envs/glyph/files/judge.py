#!/usr/bin/env python3
"""Judge for the Glyph environment."""
import os
import random
import sys
import torch

from judge_lib import (FAILURE_ARTIFACT_MISSING, FAILURE_REWARD_DENIAL, FAILURE_RUNTIME_ERROR,
                       FAILURE_TRAINING_FAILED, ORIGINALS_DIR, base_result, emit, eval_env,
                       judge_event, make_workdir, mark_check, prediction_coverage, prediction_entropy, run,
                       score_from_accuracy, scrub_workdir, set_failure, set_metric,
                       train_env, validate_checkpoint, validate_logits, validate_submission, require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
JUDGE_SEED = int(os.environ.get("JUDGE_SEED", "0"))
SEED_OFFSET = 900719925474099


def generate_evaluation_data(workdir: str) -> torch.Tensor:
    sys.path.insert(0, ORIGINALS_DIR)
    from dataset import generate_glyph, NUM_CLASSES
    from torchvision import transforms
    tfm = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5,), (0.5,))])
    rng = random.Random(JUDGE_SEED + SEED_OFFSET)
    inputs, labels = [], []
    for _ in range(2000):
        class_id = rng.randint(0, NUM_CLASSES - 1)
        random.seed(rng.randint(0, 2**32))
        inputs.append(tfm(generate_glyph(class_id, img_size=%%EVAL_IMG_SIZE%%)))
        labels.append(class_id)
    torch.save(torch.stack(inputs), os.path.join(workdir, "eval_inputs.pt"))
    return torch.tensor(labels, dtype=torch.long)


def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="< 60%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"model.py", "train.py"})
    workdir, original_files = make_workdir(patched_dir)
    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 1200, train_env(workdir))
    if tr.returncode != 0:
        set_failure(result, FAILURE_TRAINING_FAILED, "Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    mark_check(result, "training_completed")
    judge_event(result, "train", "ok", "training script completed")
    checkpoint = os.path.join(workdir, "glyph_model.pth")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        set_failure(result, FAILURE_ARTIFACT_MISSING, str(exc))
        emit(result)
    result["model_saved"] = True
    mark_check(result, "artifact_found")
    scrub_workdir(workdir, original_files, {"glyph_model.pth"})
    labels = generate_evaluation_data(workdir)
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write("import sys, torch\n" + f"sys.path.insert(0, {workdir!r})\n" + "from model import load_model\nmodel = load_model('glyph_model.pth')\ninputs = torch.load('eval_inputs.pt', weights_only=True)\nwith torch.no_grad():\n    logits = torch.cat([model(inputs[i:i+128]) for i in range(0, inputs.shape[0], 128)], dim=0)\ntorch.save(logits, 'eval_outputs.pt')\n")
    ep = run([sys.executable, eval_script], workdir, 120, eval_env())
    if ep.returncode != 0:
        set_failure(result, FAILURE_RUNTIME_ERROR, "Evaluation failed:\n" + ep.stderr[-500:])
        emit(result)
    try:
        logits = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True, map_location="cpu")
        logits = validate_logits(logits, labels, 10)
        preds = logits.argmax(1)
        accuracy = (preds == labels).float().mean().item()
        entropy = prediction_entropy(preds, 10)
        coverage = prediction_coverage(preds)
        set_metric(result, "prediction_entropy", round(entropy, 6))
        set_metric(result, "predicted_classes", coverage)
        anti_gaming_passed = coverage >= 7 and entropy >= 1.5

        # --- behavioral probes: attribute *why* accuracy is low -----------
        # The eval set draws each class many times at random spatial positions.
        # A spatially invariant classifier predicts the same label for a given
        # class regardless of where its shapes land, so per-class prediction
        # agreement (fraction matching that class's modal prediction) is a direct
        # invariance measure that does not depend on labels being correct.
        agreements = []
        for c in range(10):
            mask = labels == c
            if int(mask.sum()) == 0:
                continue
            class_preds = preds[mask]
            modal_frac = torch.bincount(class_preds, minlength=10).max().item() / int(mask.sum())
            agreements.append(modal_frac)
        spatial_agreement = float(sum(agreements) / len(agreements)) if agreements else 0.0
        set_metric(result, "spatial_prediction_agreement", round(spatial_agreement, 6))

        # Optimizer/architecture pathology: the model never learned to use its
        # capacity and emits a near-degenerate distribution.
        optimizer_ok = anti_gaming_passed
        mark_check(result, "optimization_progressed", optimizer_ok)
        judge_event(result, "check", "ok" if optimizer_ok else "fail", "optimization_progressed")
        if not optimizer_ok:
            result["notes"].append("optimizer_pathology_unfixed")

        # Spatial invariance: predictions are inconsistent across positions for
        # the same class even though the model is otherwise non-degenerate.
        spatial_ok = spatial_agreement >= 0.6
        mark_check(result, "spatial_invariance_learned", spatial_ok)
        judge_event(result, "check", "ok" if spatial_ok else "fail", "spatial_invariance_learned")
        if optimizer_ok and not spatial_ok:
            result["notes"].append("spatial_invariance_not_learned")

        # Overfit spatial layout: the model is confident and consistent per class
        # (so it learned a stable mapping) yet generalizes poorly to held-out
        # random positions.
        if optimizer_ok and spatial_ok and accuracy < PARTIAL_THRESHOLD:
            result["notes"].append("overfit_spatial_layout")
    except Exception as exc:
        set_failure(result, FAILURE_REWARD_DENIAL, f"Failed to score outputs: {exc}")
        emit(result)
    score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=anti_gaming_passed)
    emit(result)


if __name__ == "__main__":
    main()
