"""Provider-free checks for generated judges and their lazily written eval scripts.

Compiling judge.py alone does not evaluate f-strings that write _eval_runner.py,
nor does it catch missing imports at score time. Do both before any live calls.
This is a smoke check, not a proof that the judge grades correctly.
"""
from __future__ import annotations

import ast
import builtins
import symtable
from pathlib import Path

_IMPLICIT_GLOBALS = frozenset(dir(builtins)) | {"__name__", "__file__", "__package__"}
_WORKDIR = "/tmp/judge-preflight"


def _check_python(source: str, filename: str) -> ast.Module:
    tree = ast.parse(source, filename=filename)
    compile(tree, filename, "exec")
    table = symtable.symtable(source, filename, "exec")
    bound = {
        symbol.get_name()
        for symbol in table.get_symbols()
        if symbol.is_assigned() or symbol.is_imported() or symbol.is_parameter()
    }
    undefined: set[str] = set()

    def visit(scope: symtable.SymbolTable) -> None:
        for symbol in scope.get_symbols():
            if (
                symbol.is_referenced()
                and symbol.is_global()
                and symbol.get_name() not in bound | _IMPLICIT_GLOBALS
            ):
                undefined.add(symbol.get_name())
        for child in scope.get_children():
            visit(child)

    visit(table)
    if undefined:
        raise ValueError(f"{filename}: undefined global name(s): {', '.join(sorted(undefined))}")
    return tree


def _render_literal(node: ast.expr, constants: dict[str, str]) -> str:
    """Render a script's string expression without executing template code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _render_literal(node.left, constants) + _render_literal(node.right, constants)
    if isinstance(node, ast.JoinedStr):
        return "".join(_render_literal(part, constants) for part in node.values)
    if isinstance(node, ast.FormattedValue):
        if (
            not isinstance(node.value, ast.Name)
            or node.value.id != "workdir"
            or node.format_spec is not None
        ):
            raise ValueError("eval script may interpolate only the judge workdir")
        if node.conversion == ord("r"):
            return repr(_WORKDIR)
        if node.conversion in (-1, ord("s")):
            return _WORKDIR
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
        and not node.args
        and len(node.keywords) == 1
        and node.keywords[0].arg == "workdir"
        and isinstance(node.keywords[0].value, ast.Name)
        and node.keywords[0].value.id == "workdir"
    ):
        try:
            return _render_literal(node.func.value, constants).format(workdir=_WORKDIR)
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(f"invalid eval-script format expression: {exc}") from exc
    raise ValueError(f"unsupported eval-script string expression: {type(node).__name__}")


def validate_generated_judge(path: Path) -> int:
    """Check judge globals, render its eval script(s), and check their globals.

    Return the count of lazy scripts checked. The judge's own Python syntax is
    already checked by the generation preflight, but not these deferred scripts.
    """
    source = path.read_text(encoding="utf-8")
    tree = _check_python(source, str(path))
    constants = {
        statement.targets[0].id: statement.value.value
        for statement in tree.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    }
    scripts = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            opened = item.context_expr
            if not (
                isinstance(opened, ast.Call)
                and isinstance(opened.func, ast.Name)
                and opened.func.id == "open"
                and opened.args
                and isinstance(opened.args[0], ast.Name)
                and opened.args[0].id == "eval_script"
                and isinstance(item.optional_vars, ast.Name)
            ):
                continue
            handle = item.optional_vars.id
            for statement in node.body:
                if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)):
                    continue
                call = statement.value
                if (
                    not isinstance(call.func, ast.Attribute)
                    or not isinstance(call.func.value, ast.Name)
                    or call.func.value.id != handle
                    or call.func.attr != "write"
                    or len(call.args) != 1
                ):
                    continue
                rendered = _render_literal(call.args[0], constants)
                _check_python(rendered, f"{path}:_eval_runner.py")
                scripts += 1
    if any(
        isinstance(node, ast.Name) and node.id == "eval_script" and isinstance(node.ctx, ast.Store)
        for node in ast.walk(tree)
    ) and not scripts:
        raise ValueError(f"{path}: eval_script declared but no eval script was checked")
    return scripts
