"""Validate that the agent's patch applies cleanly and touches only allowed files."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

PATCH_PATH = os.environ.get("JUDGE_PATCH_PATH", "/submission/agent.patch")
ORIGINALS_DIR = os.environ.get("JUDGE_ORIGINALS_DIR", "/originals")
PATCHABLE = %%PATCHABLE_FILES%%
PATCHABLE_SET = set(PATCHABLE)
MAX_PATCH_BYTES = 512 * 1024


def _normalise_patch_path(raw: str) -> str:
    path = raw.split("\t", 1)[0].strip()
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def validate_patch_paths(patch_text: str) -> None:
    """Reject patches that create, delete, or modify non-patchable files."""
    for line in patch_text.splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        path = _normalise_patch_path(line[4:])
        if path == "/dev/null":
            raise RuntimeError("Patch may not create or delete files")
        if path not in PATCHABLE_SET:
            raise RuntimeError(f"Patch touches non-patchable file: {path}")


def validate_patch() -> str:
    if not os.path.isfile(PATCH_PATH):
        raise RuntimeError(f"Patch not found at {PATCH_PATH}")

    patch_size = os.path.getsize(PATCH_PATH)
    if patch_size == 0:
        raise RuntimeError("Patch file is empty")
    if patch_size > MAX_PATCH_BYTES:
        raise RuntimeError(f"Patch too large: {patch_size} bytes (limit {MAX_PATCH_BYTES})")

    with open(PATCH_PATH, encoding="utf-8") as f:
        patch_text = f.read()
    validate_patch_paths(patch_text)

    tmpdir = tempfile.mkdtemp(prefix="judge_patched_")
    for fname in PATCHABLE:
        src = os.path.join(ORIGINALS_DIR, fname)
        if os.path.isfile(src):
            shutil.copy2(src, tmpdir)

    dry = subprocess.run(
        ["patch", "--dry-run", "-p1", "-d", tmpdir, "-i", PATCH_PATH],
        capture_output=True,
        text=True,
    )
    if dry.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"Patch does not apply cleanly:\n{dry.stderr}\n{dry.stdout}")

    real = subprocess.run(
        ["patch", "-p1", "-d", tmpdir, "-i", PATCH_PATH],
        capture_output=True,
        text=True,
    )
    if real.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"Patch application failed:\n{real.stderr}\n{real.stdout}")

    unexpected = sorted(set(os.listdir(tmpdir)) - PATCHABLE_SET)
    if unexpected:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"Patch created unexpected files: {unexpected}")

    return tmpdir


if __name__ == "__main__":
    try:
        out = validate_patch()
        print(f"OK: patch applied to {out}")
    except RuntimeError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
