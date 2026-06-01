#!/usr/bin/env python3
"""Judge for the MoCo environment."""
import os
import sys
import torch
import torch.nn as nn

from judge_lib import (FAILURE_ARTIFACT_MISSING, FAILURE_REWARD_DENIAL, FAILURE_RUNTIME_ERROR,
                       FAILURE_TRAINING_FAILED, base_result, emit, eval_env, feature_variance,
                       judge_event, make_workdir, mark_check, run, score_from_accuracy, scrub_workdir,
                       set_failure, set_metric, train_env, validate_checkpoint,
                       validate_feature_tensor, validate_submission, require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%
JUDGE_SEED = int(os.environ.get("JUDGE_SEED", "0"))
SEED_OFFSET = 900719925474099
K = %%K%%

# Behavioral probe executed inside the patched workspace. It extracts held-out
# features and runs targeted subchecks (temperature sensitivity, queue
# wraparound) so the judge can attribute failures to distinct causes rather than
# only reporting final accuracy.
PROBE_SOURCE = '''
import sys, torch
sys.path.insert(0, {workdir!r})
from {model_module} import {model_class} as Model

model = Model(dim=16, K={K})
model.load_state_dict(torch.load("ckpt.pt", weights_only=True, map_location="cpu"), strict=False)
model.eval()

train_in = torch.load("eval_train_inputs.pt", weights_only=True)
test_in = torch.load("eval_test_inputs.pt", weights_only=True)

with torch.no_grad():
    # --- temperature sensitivity ---------------------------------------
    # If the temperature divides a quantity that is then re-normalized, tau
    # cancels and changing it has no effect on the encoder output.
    tau_ok = False
    for attr in ["tau", "temp", "temperature", "t"]:
        if hasattr(model, attr):
            orig = getattr(model, attr)
            if isinstance(orig, (int, float, torch.Tensor)):
                f1 = model.encoder_q(train_in[:1])
                try:
                    setattr(model, attr, orig * 2.0 if not isinstance(orig, torch.Tensor) else orig * 2)
                    f2 = model.encoder_q(train_in[:1])
                    setattr(model, attr, orig)
                    if not torch.allclose(f1, f2, atol=1e-5):
                        tau_ok = True
                        break
                except Exception:
                    pass

    # --- queue wraparound ----------------------------------------------
    # enqueue_keys must wrap when ptr + batch crosses K: tail keys land at the
    # end, the overflow wraps to the front, and ptr advances modulo K.
    queue_wrap_ok = False
    try:
        from queue_ops import enqueue_keys
        dim, k = 4, 10
        queue = torch.zeros(dim, k)
        ptr = torch.zeros(1, dtype=torch.long)
        ptr[0] = 8  # near the end
        n = 4       # crosses the boundary (8,9 then wrap to 0,1)
        keys = torch.arange(1, n * dim + 1, dtype=torch.float).reshape(n, dim)
        enqueue_keys(queue, ptr, keys)
        tail_ok = torch.allclose(queue[:, 8], keys[0]) and torch.allclose(queue[:, 9], keys[1])
        wrap_ok = torch.allclose(queue[:, 0], keys[2]) and torch.allclose(queue[:, 1], keys[3])
        ptr_ok = int(ptr[0]) == ((8 + n) % k)
        queue_wrap_ok = bool(tail_ok and wrap_ok and ptr_ok)
    except Exception:
        queue_wrap_ok = False

    train_f = model.encoder_q(train_in)
    test_f = model.encoder_q(test_in)

torch.save({{"train": train_f, "test": test_f, "tau_ok": tau_ok, "queue_wrap_ok": queue_wrap_ok}}, "eval_outputs.pt")
'''


def generate_evaluation_data(workdir: str):
    n_train, n_test = 1000, 500
    n_total = n_train + n_test
    torch.manual_seed(42)
    data = torch.zeros(n_total, 1, 16, 16)
    labels = torch.randint(0, 4, (n_total,))
    for i in range(n_total):
        label = labels[i].item()
        r0 = 2 if label < 2 else 10
        c0 = 2 if label % 2 == 0 else 10
        data[i, 0, r0:r0+4, c0:c0+4] = 1.0
    gen = torch.Generator().manual_seed(JUDGE_SEED + SEED_OFFSET)
    for i in range(n_total):
        noise = torch.randn(1, 16, 16, generator=gen) * 0.15
        sx = torch.randint(-1, 2, (1,), generator=gen).item()
        sy = torch.randint(-1, 2, (1,), generator=gen).item()
        data[i] = torch.roll((data[i] + noise).clamp(0, 1), (sx, sy), dims=(1, 2))
    torch.save(data[:n_train], os.path.join(workdir, "eval_train_inputs.pt"))
    torch.save(data[n_train:], os.path.join(workdir, "eval_test_inputs.pt"))
    return labels[:n_train], labels[n_train:]


def main() -> None:
    result = base_result(training_completed=False, checkpoint_saved=False, accuracy_bin="< 60%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"%%MODEL_FILE%%", "queue_ops.py"})
    workdir, original_files = make_workdir(patched_dir)
    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 600, train_env(workdir))
    if tr.returncode != 0:
        set_failure(result, FAILURE_TRAINING_FAILED, "Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    mark_check(result, "training_completed")
    judge_event(result, "train", "ok", "training script completed")
    checkpoint = os.path.join(workdir, "ckpt.pt")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        set_failure(result, FAILURE_ARTIFACT_MISSING, str(exc))
        emit(result)
    result["checkpoint_saved"] = True
    mark_check(result, "artifact_found")
    scrub_workdir(workdir, original_files, {"ckpt.pt"})
    train_labels, test_labels = generate_evaluation_data(workdir)
    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(PROBE_SOURCE.format(workdir=workdir, model_module="%%MODEL_MODULE%%",
                                    model_class="%%MODEL_CLASS%%", K=K))
    ep = run([sys.executable, eval_script], workdir, 120, eval_env())
    if ep.returncode != 0:
        set_failure(result, FAILURE_RUNTIME_ERROR, "Evaluation failed:\n" + ep.stderr[-500:])
        emit(result)
    try:
        outputs = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True, map_location="cpu")
        if not isinstance(outputs, dict):
            raise RuntimeError("Feature output must be a dict")
        train_feats = validate_feature_tensor(outputs.get("train"), train_labels.shape[0], "train")
        test_feats = validate_feature_tensor(outputs.get("test"), test_labels.shape[0], "test")
        train_var = feature_variance(train_feats)
        test_var = feature_variance(test_feats)
        set_metric(result, "train_feature_variance", round(train_var, 6))
        set_metric(result, "test_feature_variance", round(test_var, 6))
        anti_gaming_passed = train_var > 1e-4 and test_var > 1e-4
        if not anti_gaming_passed:
            result["notes"].append("collapsed_features")
        mark_check(result, "non_collapsed_features", anti_gaming_passed)
        judge_event(result, "check", "ok" if anti_gaming_passed else "fail", "non_collapsed_features")
        tau_ok = bool(outputs.get("tau_ok", False))
        mark_check(result, "temperature_sensitive", tau_ok)
        judge_event(result, "check", "ok" if tau_ok else "fail", "temperature_sensitive")
        if not tau_ok:
            result["notes"].append("temperature_cancelled")
        queue_wrap_ok = bool(outputs.get("queue_wrap_ok", False))
        mark_check(result, "queue_wraparound", queue_wrap_ok)
        judge_event(result, "check", "ok" if queue_wrap_ok else "fail", "queue_wraparound")
        if not queue_wrap_ok:
            result["notes"].append("queue_wrap_broken")
        probe = nn.Linear(train_feats.shape[1], 4)
        opt = torch.optim.Adam(probe.parameters(), lr=1e-2)
        crit = nn.CrossEntropyLoss()
        for _ in range(50):
            loss = crit(probe(train_feats), train_labels)
            opt.zero_grad(); loss.backward(); opt.step()
        with torch.no_grad():
            accuracy = (probe(test_feats).argmax(1) == test_labels).float().mean().item()
    except Exception as exc:
        set_failure(result, FAILURE_REWARD_DENIAL, f"Failed to score outputs: {exc}")
        emit(result)
    score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=anti_gaming_passed)
    emit(result)


if __name__ == "__main__":
    main()
