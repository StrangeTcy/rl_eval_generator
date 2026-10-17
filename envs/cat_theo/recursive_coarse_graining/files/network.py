"""Exact coarse-graining of a tiny integer spin system.

Each region has spins in {0,1} and nonnegative integer weights W[L, s, R].
The effective boundary table is T[L, R] = W[L, 0, R] + W[L, 1, R].
Two regions in series compose by T12[L, R] = sum_m T1[L, m] * T2[m, R].
All arithmetic is exact integer arithmetic. A table is a fixed point of
block-doubling when compose(T, T) equals T entrywise.

This is a 2-spin nonnegative integer toy, not a lattice model and not a
physical renormalization-group claim. The oracle recomputes tables from the
listed weights. It is not a CSP.
"""
from __future__ import annotations

import copy
import random
from typing import Any, Callable, Mapping, Optional


DIRECT = "direct"
RECURSIVE = "recursive"
FLAT = "flat"
REC_COMP = "recursive_composition"
REVEALED = "revealed"
INFERRED = "inferred"
SPINS = (0, 1)
PUBLIC_KEYS = (
    "spins",
    "regions",
    "tree",
    "calibration",
    "representation",
    "depth",
)
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "child_matters",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. Not evidence about a fixed point."""


def table_from_weights(weights: list[list[list[int]]], budget: list[int]) -> list[list[int]]:
    # weights[L][s][R]
    table = [[0, 0], [0, 0]]
    for L in SPINS:
        for R in SPINS:
            acc = 0
            for s in SPINS:
                budget[0] -= 1
                if budget[0] < 0:
                    raise OracleBudgetExceeded("coarse-graining exceeded sum budget; refusing to call this unsat")
                acc += int(weights[L][s][R])
            table[L][R] = acc
    return table


def compose_tables(t1: list[list[int]], t2: list[list[int]], budget: list[int]) -> list[list[int]]:
    out = [[0, 0], [0, 0]]
    for L in SPINS:
        for R in SPINS:
            acc = 0
            for m in SPINS:
                budget[0] -= 1
                if budget[0] < 0:
                    raise OracleBudgetExceeded("coarse-graining exceeded product budget; refusing to call this unsat")
                acc += int(t1[L][m]) * int(t2[m][R])
            out[L][R] = acc
    return out


def is_fixed_point(table: list[list[int]]) -> bool:
    doubled = compose_tables(table, table, [50_000])
    return doubled == table


def public_instance(inst: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: copy.deepcopy(inst[key]) for key in PUBLIC_KEYS}
    if inst.get("representation") == REVEALED:
        out["label_perm"] = copy.deepcopy(inst.get("label_perm") or [0, 1])
    return out


def _fp_weights() -> list[list[list[int]]]:
    # T = [[1,0],[0,0]] is a doubling fixed point. Realise it with inner spin 0 only.
    w = [[[0, 0], [0, 0]], [[0, 0], [0, 0]]]
    w[0][0][0] = 1
    return w


def _non_fp_weights() -> list[list[list[int]]]:
    w = [[[1, 1], [1, 1]], [[1, 1], [1, 1]]]
    return w


def _series_tree(names: list[str]) -> dict[str, Any]:
    node: dict[str, Any] = {"kind": "leaf", "name": names[0]}
    for nm in names[1:]:
        node = {
            "kind": "series",
            "left": node,
            "right": {"kind": "leaf", "name": nm},
        }
    return node


def _region_names(n: int) -> list[str]:
    if n == 1:
        return ["leaf"]
    if n == 2:
        return ["left", "right"]
    return [f"r{i}" for i in range(n)]


def generate_instance(*, depth: int, regime: str, representation: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    requested = int(depth)
    if requested < 1:
        raise ValueError("depth must be >= 1")
    if regime in (DIRECT, FLAT):
        # One region. Depth does not add a forest the oracle cannot evaluate.
        n = 1
        w = _fp_weights() if regime == DIRECT else _non_fp_weights()
        names = ["leaf"]
        regions = {"leaf": {"weights": w}}
        tree = {"kind": "leaf", "name": "leaf"}
        expect_fixed = regime == DIRECT
    else:
        n = requested
        names = _region_names(n)
        wsrc = _fp_weights() if regime == RECURSIVE else _non_fp_weights()
        regions = {nm: {"weights": copy.deepcopy(wsrc)} for nm in names}
        tree = _series_tree(names) if n >= 2 else {"kind": "leaf", "name": names[0]}
        expect_fixed = regime == RECURSIVE

    label_perm = [0, 1]
    if representation == INFERRED:
        label_perm = [1, 0]
    calibration = {
        "spin_pairs": [[0, 0], [1, 1]],  # visible equal-spin observations
    }
    return {
        "spins": [0, 1],
        "regions": regions,
        "tree": tree,
        "calibration": calibration,
        "representation": representation,
        "depth": n,
        "label_perm": label_perm,
        "meta": {"regime": regime, "seed": seed, "expect_fixed": expect_fixed},
    }


def effective_table(inst: Mapping[str, Any], node: Mapping[str, Any] | None = None, budget: list[int] | None = None) -> list[list[int]]:
    if budget is None:
        budget = [50_000]
    if node is None:
        node = inst["tree"]
    if node["kind"] == "leaf":
        weights = inst["regions"][node["name"]]["weights"]
        table = table_from_weights(weights, budget)
    else:
        t1 = effective_table(inst, node["left"], budget)
        t2 = effective_table(inst, node["right"], budget)
        table = compose_tables(t1, t2, budget)
    perm = list(inst.get("label_perm") or [0, 1])
    # apply spin relabelling on the boundary
    rel = [[0, 0], [0, 0]]
    for L in SPINS:
        for R in SPINS:
            rel[perm[L]][perm[R]] = table[L][R]
    return rel if node is inst["tree"] else table


def true_table_and_fixed(inst: Mapping[str, Any]) -> tuple[list[list[int]], bool]:
    # compute without applying perm twice: leaf tables in secret labels, perm at root
    budget = [50_000]

    def rec(node):
        if node["kind"] == "leaf":
            return table_from_weights(inst["regions"][node["name"]]["weights"], budget)
        return compose_tables(rec(node["left"]), rec(node["right"]), budget)

    table = rec(inst["tree"])
    perm = list(inst.get("label_perm") or [0, 1])
    rel = [[0, 0], [0, 0]]
    for L in SPINS:
        for R in SPINS:
            rel[perm[L]][perm[R]] = table[L][R]
    return rel, is_fixed_point(rel)


def relabel_instance(inst: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    foil = copy.deepcopy(inst)
    foil["label_perm"] = [1, 0] if inst.get("label_perm") == [0, 1] else [0, 1]
    foil["meta"] = dict(inst.get("meta") or {})
    foil["meta"]["presentation"] = True
    _ = rng
    return foil


def example_visible_instance() -> dict[str, Any]:
    return generate_instance(depth=1, regime=DIRECT, representation=REVEALED, seed=0)


def reference_certificate(inst: Mapping[str, Any]) -> dict[str, Any]:
    table, fixed = true_table_and_fixed(inst)
    return {"table": table, "fixed": bool(fixed)}


def verify_certificate(inst: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, dict):
        return False, "not a dict"
    if "table" not in raw or "fixed" not in raw:
        return False, "table/fixed missing"
    if type(raw["fixed"]) is not bool:
        return False, "fixed must be a bool"
    true_table, true_fixed = true_table_and_fixed(inst)
    try:
        got = [[int(raw["table"][i][j]) for j in SPINS] for i in SPINS]
    except Exception:
        return False, "table"
    if got != true_table:
        return False, "table mismatch"
    if raw["fixed"] is not true_fixed:
        return False, "fixed mismatch"
    return True, "ok"


def evaluate_solver(solve_fn: Callable, inst: dict[str, Any]) -> bool:
    try:
        raw = solve_fn(copy.deepcopy(public_instance(inst)))
    except Exception:
        return False
    ok, _ = verify_certificate(inst, raw)
    return ok


def arm_reference(inst: Mapping[str, Any]) -> dict[str, Any]:
    return reference_certificate(inst)


def arm_local_only(inst: Mapping[str, Any]) -> dict[str, Any]:
    """Baseline: table of the first listed region, ignore composition."""
    name = next(iter(inst["regions"]))
    table = table_from_weights(inst["regions"][name]["weights"], [50_000])
    return {"table": table, "fixed": True}


def build_grade_items(*, depth: int, regime: str, representation: str, seed: int) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_instance(depth=depth, regime=regime, representation=representation, seed=seed)
    return [
        ("local_visible", example_visible_instance()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_instance(depth=max(depth, 2), regime=RECURSIVE, representation=representation, seed=seed + 11),
        ),
        (
            "assembled_unsat",
            generate_instance(depth=max(depth, 2), regime=REC_COMP, representation=representation, seed=seed + 13),
        ),
        ("opaque_twin", relabel_instance(configured, seed + 99)),
        (
            "child_matters",
            generate_instance(depth=2, regime=REC_COMP, representation=REVEALED, seed=seed + 17),
        ),
    ]


def grade_solver(solve_fn: Callable, *, depth: int, regime: str, representation: str, seed: int) -> dict[str, bool]:
    items = build_grade_items(depth=depth, regime=regime, representation=representation, seed=seed)
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, inst in items:
        checks[name] = evaluate_solver(solve_fn, inst)
    configured = named["configured"]
    try:
        pub = public_instance(configured)
        first = solve_fn(copy.deepcopy(pub))
        second = solve_fn(copy.deepcopy(pub))
        ok, _ = verify_certificate(configured, first)
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks
