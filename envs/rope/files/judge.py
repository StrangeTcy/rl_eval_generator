#!/usr/bin/env python3
"""Judge for the RoPE environment.

Scoring is check-fraction: the trusted score is the fraction of independent
behavioral checks that pass. Each check targets a distinct failure cause so the
judge can report *why* a submission is incomplete rather than only that it is.
"""
import math
import os
import sys
import torch

from judge_lib import (FAILURE_ARTIFACT_MISSING, FAILURE_PASS, FAILURE_REWARD_DENIAL,
                       FAILURE_RUNTIME_ERROR, FAILURE_TRAINING_FAILED, FAILURE_UNDERFIT,
                       base_result, emit, eval_env, judge_event, make_workdir, mark_check, run,
                       scrub_workdir, set_failure, set_metric, train_env,
                       validate_checkpoint, validate_submission, require_changed_files)

TOTAL_HIDDEN_CHECKS = %%SCORING_TOTAL_CHECKS%%
HIDDEN_LONG_SEQ = %%HIDDEN_LONG_SEQ%%
HIDDEN_OFFSET = %%HIDDEN_OFFSET%%
JUDGE_SEED = int(os.environ.get("JUDGE_SEED", "0"))
# SEED_OFFSET: Large prime used to derive a different random seed for evaluation data.
# This ensures evaluation data differs from training data even when JUDGE_SEED is small.
SEED_OFFSET = 900719925474099

# Write probe as a standalone module instead of using string formatting.
# This avoids code injection vulnerabilities from .format() with untrusted values.
PROBE_MODULE_TEMPLATE = '''import math
import sys
import torch

# Configuration passed via command-line arguments, not string interpolation
workdir = sys.argv[1]
seed_value = int(sys.argv[2])
long_seq_value = int(sys.argv[3])

sys.path.insert(0, workdir)
torch.manual_seed(seed_value)

from rope import RotaryEmbedding
from attention import RotaryFeatureProjector
from cache import PositionCache
from model import TinyRoPEModel

checks = {}
notes = []

# --- check: rope_pairing -------------------------------------------------
try:
    rope = RotaryEmbedding(dim=8)
    x = torch.randn(2, 2, 6, 8)
    y = rope.apply_rope(x, offset=0)
    pairing_ok = bool(torch.allclose(x.norm(dim=-1), y.norm(dim=-1), atol=1e-4))
    checks["rope_pairing"] = pairing_ok
    if not pairing_ok:
        notes.append("rope_pairing_wrong")
except Exception as exc:
    checks["rope_pairing"] = False
    notes.append("rope_pairing_error: " + repr(exc))

# --- check: rope_offset --------------------------------------------------
try:
    rope = RotaryEmbedding(dim=8)
    x = torch.randn(1, 1, 3, 8)
    via_offset = rope.apply_rope(x, offset=5)
    via_positions = rope.apply_rope(x, positions=torch.arange(5, 5 + 3))
    offset_ok = bool(torch.allclose(via_offset, via_positions, atol=1e-4))
    moved = not torch.allclose(rope.apply_rope(x, offset=0), via_offset, atol=1e-4)
    offset_ok = offset_ok and moved
    checks["rope_offset"] = offset_ok
    if not offset_ok:
        notes.append("rope_offset_ignored")
except Exception as exc:
    checks["rope_offset"] = False
    notes.append("rope_offset_error: " + repr(exc))

# --- check: cache_state --------------------------------------------------
try:
    cache = PositionCache()
    s0 = cache.position_offset()
    cache.append(7)
    s1 = cache.position_offset()
    cache.append(5)
    s2 = cache.position_offset()
    cache_ok = (s0 == 0 and s1 == 7 and s2 == 12)
    checks["cache_state"] = bool(cache_ok)
    if not cache_ok:
        notes.append("cache_state_not_updated")
except Exception as exc:
    checks["cache_state"] = False
    notes.append("cache_state_error: " + repr(exc))

# --- check: attention_offset_propagated ----------------------------------
try:
    proj = RotaryFeatureProjector(dim=8, heads=2)
    proj.eval()
    x = torch.randn(1, 8, 8)
    with torch.no_grad():
        q_full, _ = proj.apply_full(x)
        cache = PositionCache()
        q_c0, _ = proj.apply_chunk(x[:, :4], cache)
        q_c1, _ = proj.apply_chunk(x[:, 4:], cache)
    prop_ok = bool(torch.allclose(q_c1, q_full[:, :, 4:], atol=1e-4))
    checks["attention_offset_propagated"] = prop_ok
    if not prop_ok:
        notes.append("attention_offset_not_propagated")
except Exception as exc:
    checks["attention_offset_propagated"] = False
    notes.append("attention_offset_error: " + repr(exc))

# --- check: chunked_equals_full (long-context integration) ----------------
try:
    model = TinyRoPEModel(dim=8, heads=2)
    model.eval()
    seq = long_seq_value
    x = torch.randn(1, seq, 8)
    with torch.no_grad():
        q_full, k_full = model.forward_full(x)
        q_chunk, k_chunk = model.forward_chunked(x, chunk_size=5)
    max_dq = float((q_full - q_chunk).abs().max().item())
    max_dk = float((k_full - k_chunk).abs().max().item())
    equiv_ok = math.isfinite(max_dq) and math.isfinite(max_dk) and max(max_dq, max_dk) < 1e-3
    checks["chunked_equals_full"] = bool(equiv_ok)
    if not equiv_ok:
        notes.append("chunked_equivalence_failed")
except Exception as exc:
    checks["chunked_equals_full"] = False
    notes.append("chunked_equivalence_error: " + repr(exc))

torch.save({"checks": checks, "notes": notes}, "eval_outputs.pt")
'''


def main() -> None:
    result = base_result(training_completed=False, checkpoint_saved=False, accuracy_bin="< 60%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"rope.py", "attention.py", "cache.py"})
    workdir, original_files = make_workdir(patched_dir)

    # Sanity train run: the patched code must still import and run end-to-end.
    tr = run([sys.executable, os.path.join(workdir, "train.py")], workdir, 600, train_env(workdir))
    if tr.returncode != 0:
        set_failure(result, FAILURE_TRAINING_FAILED, "Training failed:\n" + tr.stderr[-1000:])
        emit(result)
    result["training_completed"] = True
    mark_check(result, "training_completed")
    judge_event(result, "train", "ok", "training script completed")
    checkpoint = os.path.join(workdir, "rope_smoke.pth")
    try:
        validate_checkpoint(checkpoint)
    except RuntimeError as exc:
        set_failure(result, FAILURE_ARTIFACT_MISSING, str(exc))
        emit(result)
    result["checkpoint_saved"] = True
    mark_check(result, "artifact_found")
    scrub_workdir(workdir, original_files, {"rope_smoke.pth"})

    probe_path = os.path.join(workdir, "_eval_runner.py")
    with open(probe_path, "w", encoding="utf-8") as f:
        f.write(PROBE_MODULE_TEMPLATE)
    ep = run([
        sys.executable, probe_path, workdir, 
        str(JUDGE_SEED + SEED_OFFSET), str(HIDDEN_LONG_SEQ)
    ], workdir, 180, eval_env())
    ep = run([sys.executable, probe_path], workdir, 180, eval_env())
    if ep.returncode != 0:
        set_failure(result, FAILURE_RUNTIME_ERROR, "Behavioral probe failed:\n" + ep.stderr[-1000:])
        emit(result)

    try:
        outputs = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=False, map_location="cpu")
        if not isinstance(outputs, dict) or "checks" not in outputs:
            raise RuntimeError("probe did not produce a checks dict")
        checks = {str(k): bool(v) for k, v in outputs["checks"].items()}
    except Exception as exc:
        set_failure(result, FAILURE_REWARD_DENIAL, f"Failed to score outputs: {exc}")
        emit(result)

    # Record each behavioral check and its failure-cause notes.
    for name, ok in sorted(checks.items()):
        mark_check(result, name, ok)
        judge_event(result, "check", "ok" if ok else "fail", name)
    for note in outputs.get("notes", []):
        result["notes"].append(note)

    passed = sum(1 for ok in checks.values() if ok)
    score = passed / TOTAL_HIDDEN_CHECKS
    set_metric(result, "passed_hidden_checks", passed)
    set_metric(result, "total_hidden_checks", TOTAL_HIDDEN_CHECKS)
    set_metric(result, "trusted_score", round(score, 6))
    result["raw_accuracy"] = round(score, 6)
    result["accuracy_bin"] = f"{passed}/{TOTAL_HIDDEN_CHECKS} checks"

    # Missing required cross-context edits should never let a partial solution
    # claim a full pass, even if every probed check happens to pass.
    required_ok = bool(result.get("_required_files_ok", True))
    full_pass = (passed >= TOTAL_HIDDEN_CHECKS) and required_ok
    if not required_ok:
        score = min(score, 0.95)
    result["score"] = round(float(score), 6)

    mark_check(result, "hidden_metric_passed", full_pass)
    mark_check(result, "anti_gaming_passed", required_ok)
    if full_pass:
        set_failure(result, FAILURE_PASS)
    else:
        set_failure(result, FAILURE_UNDERFIT)
    emit(result)


if __name__ == "__main__":
    main()
