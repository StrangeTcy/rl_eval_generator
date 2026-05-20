#!/usr/bin/env python3
"""Produce a unified-diff patch of the agent's changes."""
import os
import subprocess
import sys

WORKSPACE    = "/workspace"
PATCH_DEST   = "/submission/agent.patch"
ORIGINAL_DIR = "/originals"

PATCHABLE    = %%PATCHABLE_FILES%%

def main():
    os.makedirs("/submission", exist_ok=True)
    lines = []
    for fname in PATCHABLE:
        original = os.path.join(ORIGINAL_DIR, fname)
        modified = os.path.join(WORKSPACE, fname)
        if not os.path.isfile(original):
            print(f"WARNING: No original for {fname}")
            continue
        result = subprocess.run(
            ["diff", "-u",
             "--label", f"a/{fname}",
             "--label", f"b/{fname}",
             original, modified],
            capture_output=True, text=True,
        )
        if result.returncode == 2:
            print(f"ERROR: diff failed for {fname}: {result.stderr}")
            sys.exit(1)
        lines.append(result.stdout)

    patch_text = "".join(lines)
    if not patch_text.strip():
        print("No changes detected. Did you forget to edit the files?")
        sys.exit(1)

    with open(PATCH_DEST, "w", encoding="utf-8") as f:
        f.write(patch_text)

    print(f"Patch written to {PATCH_DEST}")
    for line in patch_text.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            print(f"  {line}")

if __name__ == "__main__":
    main()