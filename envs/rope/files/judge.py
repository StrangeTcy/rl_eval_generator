#!/usr/bin/env python3
"""Judge for the RoPE cross-context paper-to-implementation environment."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import torch
from judge_lib import require_changed_files

PATCH_PATH = "/submission/agent.patch"
ORIGINALS_DIR = "/originals"
JUDGE_DIR = os.path.dirname(os.path.abspath(__file__))
LONG_SEQ = %%HIDDEN_LONG_SEQ%%
OFFSET = %%HIDDEN_OFFSET%%
DIM = 8
TOTAL_HIDDEN_CHECKS = %%SCORING_TOTAL_CHECKS%%

FAILURE_PASS = "pass"
FAILURE_PATCH_MISSING = "patch_missing"
FAILURE_PATCH_INVALID = "patch_invalid"
FAILURE_SOURCE_INVALID = "source_invalid"
FAILURE_RUNTIME_ERROR = "runtime_error"
FAILURE_REWARD_DENIAL = "reward_denial"
FAILURE_OVERFIT_VISIBLE = "overfit_visible_tests"
FAILURE_UNDERFIT = "underfit"


def set_failure(result, mode, note=None):
    result["failure_mode"] = mode
    if note:
        result.setdefault("notes", []).append(note)


def mark_check(result, name, value=True):
    result.setdefault("checks", {})[name] = bool(value)


def set_metric(result, name, value):
    result.setdefault("metrics", {})[name] = value


def emit(result):
    if result.get("score", 0.0) >= 1.0 and result.get("failure_mode") in (None, "unknown"):
        result["failure_mode"] = FAILURE_PASS
    result["verdict"] = "PASS" if result.get("score", 0.0) >= 1.0 else "FAIL"
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["verdict"] == "PASS" else 1)


def run(cmd, cwd, timeout=120, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def validate_submission(result):
    if not os.path.isfile(PATCH_PATH):
        set_failure(result, FAILURE_PATCH_MISSING, "No patch found")
        emit(result)
    mark_check(result, "patch_found")
    result["patch_found"] = True
    pv = run([sys.executable, os.path.join(JUDGE_DIR, "patch_validator.py")], JUDGE_DIR, 30)
    if pv.returncode != 0:
        set_failure(result, FAILURE_PATCH_INVALID, pv.stdout + pv.stderr)
        emit(result)
    mark_check(result, "patch_valid")
    result["patch_valid"] = True
    patched_dir = next((line.split("OK: patch applied to ")[-1].strip() for line in pv.stdout.splitlines() if line.startswith("OK:")), None)
    if not patched_dir or not os.path.isdir(patched_dir):
        set_failure(result, FAILURE_PATCH_INVALID, "Could not determine patched directory")
        emit(result)
    sv = run([sys.executable, os.path.join(JUDGE_DIR, "source_validator.py"), patched_dir], JUDGE_DIR, 30)
    if sv.returncode != 0:
        set_failure(result, FAILURE_SOURCE_INVALID, sv.stdout + sv.stderr)
        emit(result)
    mark_check(result, "sources_valid")
    result["sources_valid"] = True
    return patched_dir


def reference_rope(x, positions=None, offset=0, base=10000.0):
    dim = x.shape[-1]
    if positions is None:
        positions = torch.arange(offset, offset + x.shape[-2], device=x.device)
    inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, device=x.device).float() / dim))
    angles = torch.einsum("s,d->sd", positions.float(), inv_freq)
    cos = angles.cos()
    sin = angles.sin()
    while cos.ndim < x.ndim - 1:
        cos = cos.unsqueeze(0)
        sin = sin.unsqueeze(0)
    even = x[..., 0::2]
    odd = x[..., 1::2]
    out = torch.empty_like(x)
    out[..., 0::2] = even * cos - odd * sin
    out[..., 1::2] = even * sin + odd * cos
    return out


def validate_output(name, tensor, expected_shape):
    if not isinstance(tensor, torch.Tensor):
        raise RuntimeError(f"{name} is not a tensor")
    if tuple(tensor.shape) != tuple(expected_shape):
        raise RuntimeError(f"{name} has shape {tuple(tensor.shape)}, expected {tuple(expected_shape)}")
    if not torch.isfinite(tensor).all():
        raise RuntimeError(f"{name} contains NaN or Inf")


def main():
    result = {"patch_found": False, "patch_valid": False, "sources_valid": False,
              "long_context_equivalence": False, "offset_correctness": False,
              "norm_preservation": False, "relative_position_property": False,
              "chunked_equivalence": False, "score": 0.0, "failure_mode": "unknown",
              "checks": {}, "metrics": {}, "notes": []}
    patched_dir = validate_submission(result)
    require_changed_files(result, {"rope.py", "attention.py", "cache.py"})
    workdir = tempfile.mkdtemp(prefix="judge_rope_")
    for name in os.listdir(ORIGINALS_DIR):
        shutil.copy2(os.path.join(ORIGINALS_DIR, name), workdir)
    for name in os.listdir(patched_dir):
        if name not in {"rope.py", "attention.py", "cache.py"}:
            set_failure(result, FAILURE_PATCH_INVALID, f"Unexpected patched file: {name}")
            emit(result)
        shutil.copy2(os.path.join(patched_dir, name), workdir)

    torch.manual_seed(123)
    long_x = torch.randn(2, 3, LONG_SEQ, DIM)
    offset_x = torch.randn(2, 3, 17, DIM)
    norm_x = torch.randn(2, 4, 128, DIM)
    model_x = torch.randn(2, 41, DIM)
    rel_q = torch.randn(1, 1, 1, DIM)
    rel_k = torch.randn(1, 1, 1, DIM)
    rel_positions = torch.tensor([11, 29, 111, 129])
    torch.save({"long": long_x, "offset": offset_x, "norm": norm_x, "model_x": model_x,
                "rel_q": rel_q, "rel_k": rel_k, "rel_positions": rel_positions},
               os.path.join(workdir, "rope_inputs.pt"))

    runner = os.path.join(workdir, "_rope_runner.py")
    with open(runner, "w", encoding="utf-8") as f:
        f.write("import sys, torch\n" + f"sys.path.insert(0, {workdir!r})\n" + "from rope import RotaryEmbedding\nfrom model import TinyRoPEModel\nrope = RotaryEmbedding(dim=8)\nmodel = TinyRoPEModel(dim=8, heads=2)\ninputs = torch.load('rope_inputs.pt', weights_only=True)\nrel_pos = inputs['rel_positions']\nq_full, k_full = model.forward_full(inputs['model_x'])\nq_chunk, k_chunk = model.forward_chunked(inputs['model_x'], chunk_size=7)\noutputs = {\n    'long': rope.apply_rope(inputs['long']),\n    'offset': rope.apply_rope(inputs['offset'], offset=" + str(OFFSET) + "),\n    'norm': rope.apply_rope(inputs['norm'], offset=9),\n    'q_full': q_full,\n    'k_full': k_full,\n    'q_chunk': q_chunk,\n    'k_chunk': k_chunk,\n    'rel_q_a': rope.apply_rope(inputs['rel_q'], positions=rel_pos[0:1]),\n    'rel_k_a': rope.apply_rope(inputs['rel_k'], positions=rel_pos[1:2]),\n    'rel_q_b': rope.apply_rope(inputs['rel_q'], positions=rel_pos[2:3]),\n    'rel_k_b': rope.apply_rope(inputs['rel_k'], positions=rel_pos[3:4]),\n}\ntorch.save(outputs, 'rope_outputs.pt')\n")
    ep = run([sys.executable, runner], workdir, 120, {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"})
    if ep.returncode != 0:
        set_failure(result, FAILURE_RUNTIME_ERROR, "Evaluation subprocess failed:\n" + ep.stderr[-1000:])
        emit(result)

    try:
        outputs = torch.load(os.path.join(workdir, "rope_outputs.pt"), weights_only=True, map_location="cpu")
        validate_output("long", outputs.get("long"), long_x.shape)
        validate_output("offset", outputs.get("offset"), offset_x.shape)
        validate_output("norm", outputs.get("norm"), norm_x.shape)
        long_expected = reference_rope(long_x)
        offset_expected = reference_rope(offset_x, offset=OFFSET)
        result["long_context_equivalence"] = bool(torch.allclose(outputs["long"], long_expected, atol=1e-5, rtol=1e-5))
        result["offset_correctness"] = bool(torch.allclose(outputs["offset"], offset_expected, atol=1e-5, rtol=1e-5))
        result["norm_preservation"] = bool(torch.allclose(outputs["norm"].norm(dim=-1), norm_x.norm(dim=-1), atol=1e-5, rtol=1e-5))
        result["chunked_equivalence"] = bool(torch.allclose(outputs["q_full"], outputs["q_chunk"], atol=1e-5, rtol=1e-5) and torch.allclose(outputs["k_full"], outputs["k_chunk"], atol=1e-5, rtol=1e-5))
        for name in ["long_context_equivalence", "offset_correctness", "norm_preservation", "chunked_equivalence"]:
            mark_check(result, name, result[name])
        score_a = (outputs["rel_q_a"] * outputs["rel_k_a"]).sum(dim=-1)
        score_b = (outputs["rel_q_b"] * outputs["rel_k_b"]).sum(dim=-1)
        result["relative_position_property"] = bool(torch.allclose(score_a, score_b, atol=1e-5, rtol=1e-5))
        mark_check(result, "relative_position_property", result["relative_position_property"])
    except Exception as exc:
        set_failure(result, FAILURE_REWARD_DENIAL, f"Scoring failed: {exc}")
        emit(result)

    passed = sum([result["long_context_equivalence"], result["offset_correctness"],
                  result["norm_preservation"], result["relative_position_property"],
                  result["chunked_equivalence"]])
    required_ok = bool(result.get("_required_files_ok", True))
    set_metric(result, "passed_hidden_checks", passed)
    set_metric(result, "total_hidden_checks", TOTAL_HIDDEN_CHECKS)
    result["score"] = round(passed / TOTAL_HIDDEN_CHECKS, 6)
    if passed == TOTAL_HIDDEN_CHECKS and required_ok:
        set_failure(result, FAILURE_PASS)
        mark_check(result, "hidden_metric_passed")
        mark_check(result, "anti_gaming_passed")
    elif result["norm_preservation"] and not (result["long_context_equivalence"] and result["offset_correctness"] and result["chunked_equivalence"]):
        set_failure(result, FAILURE_OVERFIT_VISIBLE, "Short/norm behavior passed but long, offset, or chunked checks failed")
        mark_check(result, "anti_gaming_passed", False)
    else:
        set_failure(result, FAILURE_UNDERFIT)
        mark_check(result, "anti_gaming_passed", required_ok)
    if not required_ok:
        result["score"] = min(result["score"], 0.95)
    emit(result)


if __name__ == "__main__":
    main()
