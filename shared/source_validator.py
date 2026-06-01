"""AST-level integrity validation — allowlist approach."""
import ast
import os
import sys
from typing import List, Set

PATCHABLE = %%PATCHABLE_FILES%%
EXTRA_IMPORTS = {%%EXTRA_ALLOWED_IMPORTS%%}

ALLOWED_IMPORTS: Set[str] = frozenset({
    "torch", "torchvision",
    "math", "random", "collections", "functools", "itertools",
    "typing", "dataclasses", "enum", "abc", "copy",
    "numbers", "operator", "string", "textwrap",
    "PIL", "numpy", "warnings", "contextlib", "time",
}).union(EXTRA_IMPORTS)

BANNED_NAMES: Set[str] = frozenset({
    "exec", "eval", "compile", "__import__", "open",
    "globals", "locals", "vars",
    "__builtins__", "__loader__", "__spec__",
    "breakpoint",
})

class SecurityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in ALLOWED_IMPORTS:
                self.violations.append(
                    f"Line {node.lineno}: disallowed import '{alias.name}' "
                    f"(top-level '{top}' not in allowlist)"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            top = node.module.split(".")[0]
            if top not in ALLOWED_IMPORTS:
                self.violations.append(
                    f"Line {node.lineno}: disallowed from-import '{node.module}' "
                    f"(top-level '{top}' not in allowlist)"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Only bare-name calls (e.g. ``eval(...)``, ``exec(...)``) reference the
        # dangerous builtins. Attribute calls such as ``model.eval()``,
        # ``re.compile()`` or ``f.open()`` are ordinary methods and must not be
        # flagged, otherwise legitimate PyTorch solutions (which call
        # ``model.eval()``/``model.train()``) are rejected.
        if isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
            self.violations.append(f"Line {node.lineno}: banned call '{node.func.id}()'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id in BANNED_NAMES:
            self.violations.append(f"Line {node.lineno}: banned name '{node.id}'")
        self.generic_visit(node)


def validate_directory(source_dir: str) -> List[str]:
    all_violations: List[str] = []
    for fname in PATCHABLE:
        fpath = os.path.join(source_dir, fname)
        if not os.path.isfile(fpath):
            continue
        with open(fpath, encoding="utf-8") as f:
            source = f.read()
        try:
            tree = ast.parse(source, filename=fname)
        except SyntaxError as e:
            all_violations.append(f"{fname}: SyntaxError: {e}")
            continue
        visitor = SecurityVisitor()
        visitor.visit(tree)
        for v in visitor.violations:
            all_violations.append(f"{fname}: {v}")
    return all_violations


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: source_validator.py <source_dir>")
        sys.exit(1)
    violations = validate_directory(sys.argv[1])
    if violations:
        print("VIOLATIONS:")
        for v in violations:
            print(f"  {v}")
        sys.exit(1)
    print("OK: all imports on allowlist, no banned names found")
    sys.exit(0)