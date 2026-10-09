#!/usr/bin/env python3
"""One-shot vendoring of accepted CS001-CS011 artifacts into rl_eval_generator.

Policy (user-approved, 2026-10-07):
- Module and test bodies are preserved byte-for-byte.
- The ONLY transformation is import lines:
  * intra-package sibling imports become relative imports (from .mod import ...)
    so the package works both as shared.epistemic_semantics (repo) and as
    epistemic_semantics (shipped into generated judge images);
  * test imports of approved modules become absolute shared.epistemic_semantics
    imports.
- Source blob SHAs are recorded; every non-import line is verified identical.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path("/home/user/epistemic-compiler/mission-02/snippet_reconciliation/approved")
DST_PKG = Path("shared/epistemic_semantics")
DST_TESTS = Path("tests/epistemic_semantics")

MODULES = [
    "event_bayes", "supplied_policy", "epistemic_relations", "public_announcements",
    "silence", "common_knowledge", "fragmented_observation",
]
TESTS = [
    "test_event_bayes", "test_supplied_policy", "test_epistemic_relations",
    "test_public_announcements", "test_silence", "test_common_knowledge",
    "test_fragmented_observation", "test_source_e1_fixtures", "test_source_e2_fixtures",
    "test_source_e3_fixtures", "test_source_e4_fixtures",
]

def blob_sha(p: Path) -> str:
    h = subprocess.run(["git", "-C", str(SRC.parents[2]), "hash-object", str(p)],
                       capture_output=True, text=True, check=True)
    return h.stdout.strip()

def transform(lines: list[str], names: set[str], style: str) -> list[str]:
    out = []
    for line in lines:
        s = line.rstrip("\n")
        m_from = re.match(r"^from (\w+) import (.*)$", s)
        m_imp = re.match(r"^import (\w+)$", s)
        if m_from and m_from.group(1) in names:
            mod, rest = m_from.group(1), m_from.group(2)
            if style == "relative":
                out.append(f"from .{mod} import {rest}\n"); continue
            out.append(f"from shared.epistemic_semantics.{mod} import {rest}\n"); continue
        if m_imp and m_imp.group(1) in names:
            mod = m_imp.group(1)
            if style == "relative":
                out.append(f"from . import {mod}\n"); continue
            out.append(f"from shared.epistemic_semantics import {mod}\n"); continue
        out.append(line)
    return out

def strip_import_lines(lines: list[str], names: set[str]) -> list[str]:
    kept = []
    for line in lines:
        s = line.rstrip("\n")
        m_from = re.match(r"^from (\w+) import", s)
        m_from_rel = re.match(r"^from (?:\.|shared\.epistemic_semantics\.?)(\w*) import", s)
        m_imp = re.match(r"^import (\w+)$", s)
        if (m_from and m_from.group(1) in names) or (m_imp and m_imp.group(1) in names) \
                or m_from_rel:
            continue
        kept.append(line)
    return kept

def main() -> int:
    all_names = set(MODULES) | set(TESTS)
    report = []
    for mod in MODULES:
        src = SRC / f"{mod}.py"
        text = src.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        new = transform(lines, all_names, "relative")
        (DST_PKG / f"{mod}.py").write_text("".join(new), encoding="utf-8")
        same = strip_import_lines(lines, all_names) == strip_import_lines(new, all_names)
        report.append((f"{mod}.py", blob_sha(src), "module", same))
    for tst in TESTS:
        src = SRC / f"{tst}.py"
        text = src.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        new = transform(lines, all_names, "absolute")
        (DST_TESTS / f"{tst}.py").write_text("".join(new), encoding="utf-8")
        same = strip_import_lines(lines, all_names) == strip_import_lines(new, all_names)
        report.append((f"{tst}.py", blob_sha(src), "test", same))
    ok = True
    for name, sha, kind, same in report:
        print(f"{kind:6} {name:34} blob {sha} body-identical={same}")
        ok &= same
    print("ALL BODIES IDENTICAL" if ok else "MISMATCH DETECTED")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
