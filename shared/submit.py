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
    if not os.path.isdir("/submission"):
        print(
            "No /submission volume in controller mode. Return the JSON action "
            '{"type":"submit","confirm":true} instead; the host creates the patch '
            "from your workspace. /tools/submit.py is for interactive run_eval.sh only.",
            file=sys.stderr,
        )
        sys.exit(2)
    lines = []
    changed_files = []
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
        if result.stdout:
            changed_files.append(fname)

    patch_text = "".join(lines)
    if not patch_text.strip():
        print("No changes detected. Did you forget to edit the files?")
        sys.exit(1)

    with open(PATCH_DEST, "w", encoding="utf-8") as f:
        f.write(patch_text)

    print(f"Patch written to {PATCH_DEST}")
    for fname in changed_files:
        print(f"  {fname}")

if __name__ == "__main__":
    main()
