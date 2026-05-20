#!/usr/bin/env python3
"""Judge for the Glyph environment."""
import os
import random
import sys
import torch

from judge_lib import (ORIGINALS_DIR, base_result, emit, eval_env, make_workdir, run,
                       score_from_accuracy, scrub_workdir, train_env, validate_checkpoint,
                       validate_logits, validate_submission)

PASS_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.60
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
        inputs.append(tfm(generate_glyph(class_id)))
        labels.append(class_id)
    torch.save(torch.stack(inputs), os.path.join(workdir, "eval_inputs.pt"))
    return torch.tensor(labels, dtype=torch.long)


def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="< 60%")
    patched_dir = validate_submission(result)
    workdir, original_files = make_workdir(patched_dir)
    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 1200, train_env(workdir))
    if tr.returncode != 0:
        result["notes"].append("Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    checkpoint = os.path.join(workdir, "glyph_model.pth")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        result["notes"].append(str(exc))
        emit(result)
    result["model_saved"] = True
    scrub_workdir(workdir, original_files, {"glyph_model.pth"})
    labels = generate_evaluation_data(workdir)
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write("import sys, torch\n" + f"sys.path.insert(0, {workdir!r})\n" + "from model import load_model\nmodel = load_model('glyph_model.pth')\ninputs = torch.load('eval_inputs.pt', weights_only=True)\nwith torch.no_grad():\n    logits = model(inputs)\ntorch.save(logits, 'eval_outputs.pt')\n")
    ep = run([sys.executable, eval_script], workdir, 120, eval_env())
    if ep.returncode != 0:
        result["notes"].append("Evaluation failed:\n" + ep.stderr[-500:])
        emit(result)
    try:
        logits = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True, map_location="cpu")
        logits = validate_logits(logits, labels, 10)
        accuracy = (logits.argmax(1) == labels).float().mean().item()
    except Exception as exc:
        result["notes"].append(f"Failed to score outputs: {exc}")
        emit(result)
    score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD)
    emit(result)


if __name__ == "__main__":
    main()
