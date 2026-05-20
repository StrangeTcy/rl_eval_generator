"""Shared judge utilities for generated evaluation environments."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable

import torch

PATCH_PATH = "/submission/agent.patch"
ORIGINALS_DIR = "/originals"
JUDGE_DIR = os.path.dirname(os.path.abspath(__file__))
PATCHABLE = %%PATCHABLE_FILES%%
PATCHABLE_SET = set(PATCHABLE)

MAX_CHECKPOINT_BYTES = 150 * 1024 * 1024
MAX_STATE_TENSORS = 500
MAX_STATE_ELEMENTS = 50_000_000
MAX_OUTPUT_ELEMENTS = 20_000_000


def emit(result: dict, pass_score: float = 1.0) -> None:
    result["verdict"] = "PASS" if result.get("score", 0.0) >= pass_score else "FAIL"
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["verdict"] == "PASS" else 1)


def run(cmd: list[str], cwd: str, timeout: int = 900, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def base_result(**extra) -> dict:
    result = {
        "patch_found": False,
        "patch_valid": False,
        "sources_valid": False,
        "training_completed": False,
        "raw_accuracy": 0.0,
        "score": 0.0,
        "notes": [],
    }
    result.update(extra)
    return result


def validate_submission(result: dict) -> str:
    if not os.path.isfile(PATCH_PATH):
        result["notes"].append("No patch found at /submission/agent.patch")
        emit(result)
    result["patch_found"] = True

    pv = run([sys.executable, os.path.join(JUDGE_DIR, "patch_validator.py")], cwd=JUDGE_DIR, timeout=30)
    if pv.returncode != 0:
        result["notes"].append(f"Patch validation failed:\n{pv.stdout}\n{pv.stderr}")
        emit(result)
    result["patch_valid"] = True

    patched_dir = None
    for line in pv.stdout.splitlines():
        if line.startswith("OK:"):
            patched_dir = line.split("OK: patch applied to ")[-1].strip()
            break
    if not patched_dir or not os.path.isdir(patched_dir):
        result["notes"].append("Could not determine patched directory")
        emit(result)

    unexpected = sorted(set(os.listdir(patched_dir)) - PATCHABLE_SET)
    if unexpected:
        result["notes"].append(f"Patch produced unexpected files: {unexpected}")
        emit(result)

    sv = run([sys.executable, os.path.join(JUDGE_DIR, "source_validator.py"), patched_dir], cwd=JUDGE_DIR, timeout=30)
    if sv.returncode != 0:
        result["notes"].append(f"Source validation failed:\n{sv.stdout}\n{sv.stderr}")
        emit(result)
    result["sources_valid"] = True
    return patched_dir


def make_workdir(patched_dir: str) -> tuple[str, set[str]]:
    """Copy pristine originals plus only explicitly patchable patched files."""
    workdir = tempfile.mkdtemp(prefix="judge_run_")
    original_files: set[str] = set()
    for name in os.listdir(ORIGINALS_DIR):
        shutil.copy2(os.path.join(ORIGINALS_DIR, name), workdir)
        original_files.add(name)

    for name in os.listdir(patched_dir):
        if name not in PATCHABLE_SET:
            raise RuntimeError(f"Unexpected patched file: {name}")
        shutil.copy2(os.path.join(patched_dir, name), workdir)

    return workdir, original_files


def scrub_workdir(workdir: str, original_files: set[str], allowed_artifacts: Iterable[str]) -> None:
    allowed = set(allowed_artifacts)
    for entry in os.listdir(workdir):
        full = os.path.join(workdir, entry)
        if entry in allowed or entry in original_files:
            continue
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)
        else:
            os.remove(full)


def train_env(workdir: str) -> dict:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": "/tmp",
        "PYTHONPATH": workdir,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def eval_env() -> dict:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def validate_checkpoint(path: str) -> None:
    if not os.path.isfile(path):
        raise RuntimeError(f"Checkpoint not found: {path}")
    size = os.path.getsize(path)
    if size > MAX_CHECKPOINT_BYTES:
        raise RuntimeError(f"Checkpoint too large: {size} bytes")
    state = torch.load(path, weights_only=True, map_location="cpu")
    if not isinstance(state, dict):
        raise RuntimeError("Checkpoint must be a state_dict-like mapping")
    tensors = [v for v in state.values() if isinstance(v, torch.Tensor)]
    if len(tensors) > MAX_STATE_TENSORS:
        raise RuntimeError(f"Checkpoint has too many tensors: {len(tensors)}")
    elements = sum(t.numel() for t in tensors)
    if elements > MAX_STATE_ELEMENTS:
        raise RuntimeError(f"Checkpoint has too many tensor elements: {elements}")


def validate_logits(logits: object, labels: torch.Tensor, num_classes: int | None = None) -> torch.Tensor:
    if not isinstance(logits, torch.Tensor):
        raise RuntimeError("Model output must be a tensor")
    if logits.ndim != 2:
        raise RuntimeError(f"Model output must be rank 2, got shape {tuple(logits.shape)}")
    if logits.shape[0] != labels.shape[0]:
        raise RuntimeError(f"Output batch size {logits.shape[0]} does not match labels {labels.shape[0]}")
    if num_classes is not None and logits.shape[1] < num_classes:
        raise RuntimeError(f"Output class dimension {logits.shape[1]} is less than expected {num_classes}")
    if logits.numel() > MAX_OUTPUT_ELEMENTS:
        raise RuntimeError(f"Output tensor too large: {logits.numel()} elements")
    if not torch.isfinite(logits).all():
        raise RuntimeError("Model output contains NaN or Inf")
    return logits


def validate_feature_tensor(features: object, rows: int, name: str) -> torch.Tensor:
    if not isinstance(features, torch.Tensor):
        raise RuntimeError(f"{name} features must be a tensor")
    if features.ndim != 2:
        raise RuntimeError(f"{name} features must be rank 2, got {tuple(features.shape)}")
    if features.shape[0] != rows:
        raise RuntimeError(f"{name} feature rows {features.shape[0]} != expected {rows}")
    if features.numel() > MAX_OUTPUT_ELEMENTS:
        raise RuntimeError(f"{name} feature tensor too large: {features.numel()} elements")
    if not torch.isfinite(features).all():
        raise RuntimeError(f"{name} features contain NaN or Inf")
    return features


def score_from_accuracy(result: dict, accuracy: float, pass_threshold: float, partial_threshold: float) -> None:
    result["raw_accuracy"] = round(float(accuracy), 6)
    if accuracy >= pass_threshold:
        result["score"] = 1.0
        result["accuracy_bin"] = f">= {int(pass_threshold * 100)}%"
    elif accuracy >= partial_threshold:
        result["score"] = 0.5
        result["accuracy_bin"] = f"{int(partial_threshold * 100)}% - {int(pass_threshold * 100) - 1}%"
    else:
        result["score"] = 0.0
        result["accuracy_bin"] = f"< {int(partial_threshold * 100)}%"
