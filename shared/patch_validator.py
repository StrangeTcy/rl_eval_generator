"""Validate that the agent's patch applies cleanly and touches only allowed files."""
from __future__ import annotations

import os
import re
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


_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_NO_NEWLINE = "\\ No newline at end of file"


def modified_files_from_patch(patch_text: str) -> set[str]:
    """Read actual file headers, never source lines that resemble headers.

    A deleted line beginning ``-- `` looks like ``--- `` in a diff hunk;
    likewise an added line beginning ``++ `` looks like ``+++ ``. Hunk line
    counts distinguish these from real file headers, and also prevent a
    forged header inside a Python docstring from satisfying required edits.
    """
    lines = patch_text.rstrip("\n").split("\n")
    paths: set[str] = set()
    i = 0
    while i < len(lines):
        while i < len(lines) and (lines[i].startswith("diff --git ") or lines[i].startswith("index ")):
            i += 1
        if i >= len(lines) or not lines[i].startswith("--- "):
            raise RuntimeError("Expected unified diff file header")
        old = _normalise_patch_path(lines[i][4:])
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise RuntimeError("Expected paired +++ file header")
        new = _normalise_patch_path(lines[i][4:])
        i += 1
        if old == "/dev/null" or new == "/dev/null":
            raise RuntimeError("Patch may not create or delete files")
        if old not in PATCHABLE_SET or new not in PATCHABLE_SET:
            raise RuntimeError(f"Patch touches non-patchable file: {old if old not in PATCHABLE_SET else new}")
        if old != new:
            raise RuntimeError(f"Patch may not rename files: {old} -> {new}")
        if i >= len(lines) or not lines[i].startswith("@@ "):
            raise RuntimeError(f"Patch has no unified diff hunk for {old}")
        changed = False
        while i < len(lines) and lines[i].startswith("@@ "):
            header = _HUNK.match(lines[i])
            if header is None:
                raise RuntimeError(f"Invalid unified diff hunk for {old}")
            old_remaining = int(header.group(1) or 1)
            new_remaining = int(header.group(2) or 1)
            i += 1
            while old_remaining or new_remaining:
                if i >= len(lines):
                    raise RuntimeError(f"Truncated unified diff hunk for {old}")
                line = lines[i]
                if line == _NO_NEWLINE:
                    i += 1
                    continue
                if line.startswith("-"):
                    old_remaining -= 1
                    changed = True
                elif line.startswith("+"):
                    new_remaining -= 1
                    changed = True
                elif line.startswith(" "):
                    old_remaining -= 1
                    new_remaining -= 1
                else:
                    raise RuntimeError(f"Invalid unified diff line for {old}")
                if old_remaining < 0 or new_remaining < 0:
                    raise RuntimeError(f"Invalid unified diff hunk length for {old}")
                i += 1
            while i < len(lines) and lines[i] == _NO_NEWLINE:
                i += 1
        if not changed:
            raise RuntimeError(f"Patch has no changes for {old}")
        paths.add(old)
    return paths


def validate_patch_paths(patch_text: str) -> None:
    """Reject creation, deletion, renaming, or edits outside the allowlist."""
    modified_files_from_patch(patch_text)


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
    touched_paths = modified_files_from_patch(patch_text)

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
    for name in touched_paths:
        original = os.path.join(ORIGINALS_DIR, name)
        patched = os.path.join(tmpdir, name)
        if not os.path.isfile(original) or not os.path.isfile(patched):
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(f"Patch must update an existing file: {name}")
        with open(original, "rb") as before, open(patched, "rb") as after:
            if before.read() == after.read():
                shutil.rmtree(tmpdir, ignore_errors=True)
                raise RuntimeError(f"Patch has no effective change to file: {name}")

    return tmpdir


if __name__ == "__main__":
    try:
        out = validate_patch()
        print(f"OK: patch applied to {out}")
    except RuntimeError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
