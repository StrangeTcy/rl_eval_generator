#!/usr/bin/env python3
"""Content-addressed identity of the code that produces exact-instance gate verdicts.

Why this exists. ``run_suite`` accumulates exact-instance gate rows across runner jobs,
because one gate phase costs more CPU-hours than a single Actions leg (Glyph/MoCo
reference training dominates). A row may only be reused under the same *gate context*,
and the context used to be ``git rev-parse HEAD``. That made the context change on
every commit -- a note, a launcher comment, a test -- so each commit discarded 100%
of the banked rows and the gate restarted from zero. Combined with a cron loop that
also edits the repository, the campaign could never finish gating: it died at the same
blocked-row message every tick, which reads like a stubborn failure but is a cache
invalidation bug.

The honest invariant is not "same commit" but "same verdict-producing code". Two
commits whose grading code is byte-identical cannot disagree about a reference value,
so their rows are interchangeable; one edit to an environment template or to the gate
must invalidate. This module computes that: the transitive import closure of the
verdict producers, plus every file under ``envs/`` (generated workspaces are patched
from those templates), plus the requirements the runner installs into the image.

It is deliberately over-strict in one direction -- any change under ``envs/``
invalidates, even an environment no case gates -- and it is never permissive about a
missing input: a declared file that does not exist raises, because hashing a partial
set would silently mint a context that some other, complete run would reject (or,
worse, accept).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

# Files whose bytes can change a verdict and that a static import walk cannot see.
EXPLICIT = (
    "requirements.txt",
    "arena.py",
    "env_runner.py",
    "tools/run_suite.py",
    "tools/instance_oracle_gate.py",
    "tools/instance_oracle_preflight.py",
    "tools/oracle_preflight.py",
    "tools/suite_inventory.py",
)

# Seeds for the import closure: anything these modules import from this repository is
# verdict-relevant by construction, so a new helper module is covered the moment it is
# imported rather than the moment someone remembers this list.
CLOSURE_SEEDS = (
    "tools/run_suite.py",
    "tools/instance_oracle_gate.py",
    "tools/instance_oracle_preflight.py",
    "tools/suite_inventory.py",
)

# Whole directories: generated env workspaces are patched from these sources.
DIRS = ("envs",)

PREFIX = "content-sha256:"


def _resolve_module(name: str) -> Path | None:
    """Map a top-level import to a repository file, if it is one."""
    if not name or name.startswith(".") or "." in name:
        candidate = Path(*name.split(".")) if name else None
    else:
        candidate = Path(name)
    if candidate is None:
        return None
    for rel in (f"{candidate}.py", candidate / "__init__.py"):
        path = ROOT / rel
        if path.is_file():
            return path
    return None


def _imported_names(path: Path) -> Iterable[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):  # unreadable source is handled by _digest_file
        return ()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and not node.level:
                names.add(node.module)
    return names


def verdict_relevant_files() -> list[Path]:
    """Every file whose bytes decide a gate verdict, sorted and deduplicated."""
    collected: set[Path] = set()
    missing: list[str] = []
    for rel in EXPLICIT:
        path = ROOT / rel
        if path.is_file():
            collected.add(path.resolve())
        else:
            missing.append(rel)
    for rel_dir in DIRS:
        directory = ROOT / rel_dir
        if not directory.is_dir():
            missing.append(f"{rel_dir}/")
            continue
        for path in directory.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                collected.add(path.resolve())
    # `collected` also holds the EXPLICIT files, so the walk needs its own visited set:
    # otherwise a seed that is listed in both places is skipped before its imports are
    # read, and everything it pulls in quietly escapes the context.
    queue = [ROOT / rel for rel in CLOSURE_SEEDS]
    visited: set[Path] = set()
    while queue:
        path = queue.pop()
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in visited:
            continue
        visited.add(resolved)
        collected.add(resolved)
        for name in _imported_names(path):
            imported = _resolve_module(name)
            if imported is not None:
                queue.append(imported)
    if missing:
        raise FileNotFoundError(
            "gate context is undefined because verdict-relevant inputs are missing: "
            + ", ".join(sorted(missing))
        )
    return sorted(collected)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute() -> str:
    """Digest of the verdict-relevant file set, prefixed so it is never mistaken for a
    git revision."""
    files = verdict_relevant_files()
    manifest = "\n".join(
        f"{path.relative_to(ROOT).as_posix()}  {_file_digest(path)}" for path in files
    )
    return PREFIX + hashlib.sha256(manifest.encode("utf-8")).hexdigest()


def inventory() -> dict[str, str]:
    """The covered files and their digests, for an operator who wants to audit one."""
    return {
        str(path.relative_to(ROOT).as_posix()): _file_digest(path)
        for path in verdict_relevant_files()
    }


def head() -> str | None:
    """Current revision, recorded beside the content context for provenance only."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the covered inventory")
    args = parser.parse_args()
    context = compute()
    if args.json:
        print(json.dumps({"gate_context_sha": context, "head": head(),
                         "files": inventory()}, indent=2, sort_keys=True))
    else:
        print(context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
