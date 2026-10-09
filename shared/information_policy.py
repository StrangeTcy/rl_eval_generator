"""Host-side contract for ``information_policy`` modules (decision item 5).

An information policy is the renderer-hook contract applied to *evidence
selection*: a deterministic module, declared as ``information_policy: <file>``
in the environment config, that is a pure function of ``(seed, substitutions)``,
is **shipped to the judge**, and is re-run by the judge at grading time.

Why a module and not prose: a claim about how the evidence was selected -
especially a type-3 deception claim ("this transcript was strategically
chosen") - is admissible only where the selection policy is re-derivable.
Text in a prompt is not graded.  The judge re-runs the shipped module against
the rebuilt instance spec and compares with the baked record; a mismatch is
``reward_denial``, the same precedent as the instance-spec rebuild check.

Purity rules (enforced by :func:`validate_source`, run at config-validation
time and again before every execution):

- allowed imports: a fixed stdlib allowlist plus sibling modules from the
  environment's own ``files/`` directory (``core``, ...);
- no I/O, no process, no network, no dynamic-code builtins (``open``,
  ``eval``, ``exec``, ``compile``, ``__import__``, ``getattr``, ...);
- no time/clock modules - a policy is a function of the seed, not of the wall
  clock;
- no async code;
- a top-level ``select(context)`` entry point is required.

The AST scan is the coarse gate; the proof is :func:`check_determinism`,
which runs ``select`` twice on deep copies of the same context and refuses
generation when the two outputs differ.  A policy the generator cannot
reproduce is a policy the judge cannot re-run, which is prose again.

Stdlib only: this module is imported by ``generate_env.py`` and (lazily, via
``shared.generation_manifest``) by verification paths that must not depend on
anything the environment installs.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

#: The entry point a policy module must define (generator side).
ENTRY_POINT = "select"

#: Placeholder names a policy may return (same rule as the renderer hook).
KEY_PATTERN = r"[A-Z0-9_]+"

#: Stdlib modules a policy may import.  Deliberately small: everything here is
#: deterministic and side-effect-free at import time.  ``random`` is allowed
#: because a policy may draw from ``random.Random(context["seed"])``; the
#: determinism probe is what makes that safe.
ALLOWED_STDLIB_IMPORTS = frozenset({
    "__future__",
    "ast",
    "collections",
    "dataclasses",
    "decimal",
    "fractions",
    "functools",
    "hashlib",
    "itertools",
    "json",
    "math",
    "operator",
    "pprint",
    "random",
    "re",
    "string",
    "textwrap",
    "typing",
})

#: Builtins whose mere use disqualifies a policy: I/O, dynamic code, and
#: reflective access that could re-import anything the allowlist refuses.
FORBIDDEN_CALLS = frozenset({
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "input",
    "breakpoint",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
})

#: Names that must not appear at all in policy source.  Importing these is
#: already refused; this also catches aliases and injected references
#: (``sys.path`` tricks, wall-clock reads via ``time``, ...).
FORBIDDEN_NAMES = frozenset({
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "time",
    "datetime",
    "tempfile",
    "threading",
    "multiprocessing",
    "signal",
    "ctypes",
    "importlib",
    "pickle",
    "marshal",
    "builtins",
    "__builtins__",
})


def validate_source(
    text: str,
    *,
    path: str = "<information_policy>",
    sibling_modules: Iterable[str] = (),
) -> List[str]:
    """AST purity scan of a policy source; empty list means admissible.

    ``sibling_modules`` are the ``.py`` stems in the environment's ``files/``
    directory: a policy may import the environment's own shipped engine
    (``core``), because that module is already judge-shipped and hash-pinned.
    Transitive imports of siblings are not rescanned - they carry the same
    trust class as the renderer hook's siblings.
    """
    allowed = set(ALLOWED_STDLIB_IMPORTS) | {str(m) for m in sibling_modules}
    problems: List[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"{path}: not valid Python ({exc})"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowed:
                    problems.append(
                        f"{path}:{node.lineno}: import {alias.name!r} is not allowed in an "
                        "information policy (stdlib allowlist or sibling env module only)"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(
                    f"{path}:{node.lineno}: relative imports are not allowed in an "
                    "information policy"
                )
            else:
                root = (node.module or "").split(".")[0]
                if root not in allowed:
                    problems.append(
                        f"{path}:{node.lineno}: import from {node.module!r} is not allowed in "
                        "an information policy (stdlib allowlist or sibling env module only)"
                    )
        elif isinstance(node, ast.AsyncFunctionDef) or isinstance(node, ast.Await):
            problems.append(
                f"{path}:{node.lineno}: async code is not allowed in an information policy"
            )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                problems.append(
                    f"{path}:{node.lineno}: call to {node.func.id}() is not allowed in an "
                    "information policy (no I/O, no dynamic code, no reflective access)"
                )
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(
                f"{path}:{node.lineno}: reference to {node.id!r} is not allowed in an "
                "information policy"
            )

    if not any(
        isinstance(node, ast.FunctionDef) and node.name == ENTRY_POINT
        for node in tree.body
    ):
        problems.append(
            f"{path}: must define a top-level '{ENTRY_POINT}(context)' entry point"
        )
    return problems


def sha256_file(path: Path | str) -> str:
    """Hash of a policy file's bytes (recorded in the manifest and spec)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validated_selection(filename: str, raw: Any) -> Dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"information policy {filename!r}: {ENTRY_POINT}() must return a mapping "
            "of placeholder values"
        )
    selection: Dict[str, str] = {}
    for key, value in raw.items():
        if not re.fullmatch(KEY_PATTERN, str(key)):
            raise ValueError(
                f"information policy {filename!r} returned invalid placeholder name "
                f"{key!r} (keys must match {KEY_PATTERN})"
            )
        selection[str(key)] = str(value)
    return selection


def load_policy(files_dir: Path | str, filename: str) -> Any:
    """Load a policy module in isolation, mirroring the renderer loader.

    Re-validates purity on every load: the file on disk at generation time is
    the declaration, not whatever passed config validation earlier.
    """
    files_dir = Path(files_dir)
    policy_path = files_dir / filename
    if not policy_path.is_file():
        raise FileNotFoundError(f"information policy not found: {policy_path}")
    if policy_path.is_symlink():
        raise ValueError(f"information policy is a symlink: {policy_path}")
    problems = validate_source(
        policy_path.read_text(encoding="utf-8"),
        path=filename,
        sibling_modules={p.stem for p in files_dir.glob("*.py")},
    )
    if problems:
        raise ValueError(
            f"information policy {filename!r} is not admissible: " + "; ".join(problems)
        )
    spec = importlib.util.spec_from_file_location(
        f"env_information_policy_{policy_path.stem}", policy_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load information policy module: {policy_path}")
    module = importlib.util.module_from_spec(spec)
    # Allow the policy to import sibling modules (e.g. the env's core).
    sys.path.insert(0, str(files_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    if not callable(getattr(module, ENTRY_POINT, None)):
        raise ValueError(
            f"information policy {filename!r} must define {ENTRY_POINT}(context)"
        )
    return module


def check_determinism(
    files_dir: Path | str,
    filename: str,
    context: Mapping[str, Any],
) -> Dict[str, str]:
    """Run ``select`` twice on deep copies; refuse non-deterministic policies.

    Returns the validated selection (both runs agreed).  ``context`` carries
    ``{"seed": int, "subs": dict}``; deep copies keep a policy that mutates
    its input from passing the probe by accident.
    """
    module = load_policy(files_dir, filename)
    first = _validated_selection(filename, module.select(copy.deepcopy(dict(context))))
    second = _validated_selection(filename, module.select(copy.deepcopy(dict(context))))
    if first != second:
        raise ValueError(
            f"information policy {filename!r}: {ENTRY_POINT}() is not deterministic - "
            "two runs on the same context produced different selections; a policy the "
            "judge cannot reproduce is prose, not a declaration"
        )
    return first
