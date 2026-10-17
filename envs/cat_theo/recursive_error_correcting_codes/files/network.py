"""Recursive linear codes over a prime field.

Each block has a parity-check matrix over F_p. A child contributes symbols to
its parent through a coordinate permutation (and optional nonzero scale). The
oracle multiplies matrices by vectors in F_p; it does not call a generic CSP
solver. Local kernels may be nonempty while the stacked overlap system is not.
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
PUBLIC_KEYS = (
    "modulus",
    "blocks",
    "glues",
    "parent_check",
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
    "explicit_expand",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. Not a decoding failure."""


def add(a: int, b: int, p: int) -> int:
    return (int(a) + int(b)) % p


def mul(a: int, b: int, p: int) -> int:
    return (int(a) * int(b)) % p


def matvec(matrix: list[list[int]], vec: list[int], p: int) -> list[int]:
    out = []
    for row in matrix:
        s = 0
        for a, x in zip(row, vec):
            s = add(s, mul(a, x, p), p)
        out.append(s)
    return out


def kernel_nonempty(matrix: list[list[int]], p: int, budget: list[int]) -> bool:
    width = len(matrix[0]) if matrix else 0
    # brute force: p^width with width <= 3
    from itertools import product

    for vec in product(range(p), repeat=width):
        budget[0] -= 1
        if budget[0] < 0:
            raise OracleBudgetExceeded("code oracle exceeded enumeration budget; refusing to call this unsat")
        if all(v == 0 for v in matvec(matrix, list(vec), p)):
            return True
    return False


def public_instance(inst: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: copy.deepcopy(inst[key]) for key in PUBLIC_KEYS}
    if inst.get("representation") == REVEALED:
        out["perms"] = copy.deepcopy(inst["perms"])
    return out


def generate_instance(*, depth: int, regime: str, representation: str, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    p = 5
    n = int(depth)
    if n < 1:
        raise ValueError("depth must be >= 1")
    # One length-2 block per depth unit. Local check [1,1] · v = 0.
    names = [chr(ord("A") + i) for i in range(n)]
    blocks = {nm: {"length": 2, "H": [[1, 1]]} for nm in names}
    glues: list[dict[str, Any]] = []
    if regime in (RECURSIVE, REC_COMP) and n >= 2:
        for i in range(n - 1):
            glues.append({"left": [names[i], 1], "right": [names[i + 1], 0], "scale": 1})
        glues.append({"left": [names[-1], 1], "right": [names[0], 0], "scale": 1})
    parent_vars = [[nm, 0] for nm in names]
    if regime == REC_COMP:
        if n == 1:
            parent_check = {"vars": [["A", 0], ["A", 1]], "row": [1, 1], "rhs": 1}
        else:
            parent_check = {"vars": parent_vars, "row": [1] * n, "rhs": 1}
    else:
        if regime == DIRECT and n == 1:
            parent_check = {"vars": [["A", 0], ["A", 1]], "row": [1, 1], "rhs": 0}
        else:
            parent_check = {"vars": parent_vars, "row": [1] * n, "rhs": 0}
        if regime in (DIRECT, FLAT):
            glues = []

    perms = {name: list(range(spec["length"])) for name, spec in blocks.items()}
    if representation == INFERRED and n > 1:
        perms[names[1]] = [1, 0]
    _ = rng  # seed reserved for future sampled checks; perms are deterministic
    calibration = {}
    for name, spec in blocks.items():
        words = []
        for x in range(p):
            vec = [0] * spec["length"]
            vec[0] = x
            if spec["length"] == 2 and spec["H"] == [[1, 1]]:
                vec[1] = (-x) % p
            words.append(vec)
        calibration[name] = words[:2]
    return {
        "modulus": p,
        "blocks": blocks,
        "glues": glues,
        "parent_check": parent_check,
        "calibration": calibration,
        "representation": representation,
        "depth": n,
        "perms": perms,
        "meta": {"regime": regime, "seed": seed},
    }


def _apply_perm(vec: list[int], perm: list[int]) -> list[int]:
    out = [0] * len(vec)
    for i, src in enumerate(perm):
        out[i] = vec[src]
    return out


def stacked_satisfiable(inst: Mapping[str, Any], budget: int = 80_000) -> bool:
    p = int(inst["modulus"])
    names = list(inst["blocks"])
    lengths = {n: inst["blocks"][n]["length"] for n in names}
    from itertools import product

    ranges = []
    index = []
    for n in names:
        ranges.append(range(p ** lengths[n]))
        index.append(n)
    # width total <= 6, p=5 -> 5^6 = 15625, OK
    dims = [lengths[n] for n in names]
    total = 1
    for d in dims:
        total *= p ** d
    count = 0
    coords = [range(p) for _ in range(sum(dims))]
    for vec in product(*coords):
        count += 1
        if count > budget:
            raise OracleBudgetExceeded("code oracle exceeded enumeration budget; refusing to call this unsat")
        assignment: dict[str, list[int]] = {}
        k = 0
        for n in names:
            L = lengths[n]
            assignment[n] = list(vec[k : k + L])
            k += L
        ok = True
        for n, spec in inst["blocks"].items():
            if any(v != 0 for v in matvec(spec["H"], assignment[n], p)):
                ok = False
                break
        if not ok:
            continue
        perms = inst["perms"]
        vis = {n: _apply_perm(assignment[n], perms[n]) for n in names}
        for glue in inst["glues"]:
            ln, li = glue["left"]
            rn, ri = glue["right"]
            left = vis[ln][li]
            right = mul(glue["scale"], vis[rn][ri], p)
            if left != right:
                ok = False
                break
        if not ok:
            continue
        parent = inst["parent_check"]
        acc = 0
        for coeff, (bn, bi) in zip(parent["row"], parent["vars"]):
            acc = add(acc, mul(coeff, vis[bn][bi], p), p)
        if acc == int(parent["rhs"]) % p:
            return True
    return False


def local_kernels_nonempty(inst: Mapping[str, Any]) -> bool:
    p = int(inst["modulus"])
    for spec in inst["blocks"].values():
        if not kernel_nonempty(spec["H"], p, [50_000]):
            return False
    return True


def relabel_instance(inst: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    p = int(inst["modulus"])
    scale = rng.choice([1, 2, 3, 4])
    foil = copy.deepcopy(inst)
    # scale all symbols in checks: H' = H (invariant for [1,1] if we scale vec)
    foil["meta"] = dict(inst.get("meta") or {})
    foil["meta"]["symbol_scale"] = scale
    return foil


def example_visible_instance() -> dict[str, Any]:
    return generate_instance(depth=1, regime=DIRECT, representation=REVEALED, seed=0)


def reference_certificate(inst: Mapping[str, Any]) -> dict[str, Any]:
    p = int(inst["modulus"])
    names = list(inst["blocks"])
    lengths = {n: inst["blocks"][n]["length"] for n in names}
    from itertools import product

    dims = [lengths[n] for n in names]
    coords = [range(p) for _ in range(sum(dims))]
    for vec in product(*coords):
        assignment: dict[str, list[int]] = {}
        k = 0
        for n in names:
            L = lengths[n]
            assignment[n] = list(vec[k : k + L])
            k += L
        foil = copy.deepcopy(inst)
        # reuse stacked check on a singleton by injecting
        if _assignment_ok(inst, assignment):
            return {"status": "sat", "blocks": assignment}
    return {"status": "unsat"}


def _assignment_ok(inst: Mapping[str, Any], assignment: Mapping[str, list[int]]) -> bool:
    p = int(inst["modulus"])
    for n, spec in inst["blocks"].items():
        if any(v != 0 for v in matvec(spec["H"], assignment[n], p)):
            return False
    perms = inst["perms"]
    vis = {n: _apply_perm(assignment[n], perms[n]) for n in assignment}
    for glue in inst["glues"]:
        ln, li = glue["left"]
        rn, ri = glue["right"]
        if vis[ln][li] != mul(glue["scale"], vis[rn][ri], p):
            return False
    parent = inst["parent_check"]
    acc = 0
    for coeff, (bn, bi) in zip(parent["row"], parent["vars"]):
        acc = add(acc, mul(coeff, vis[bn][bi], p), p)
    return acc == int(parent["rhs"]) % p


def verify_certificate(inst: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, dict) or raw.get("status") not in ("sat", "unsat"):
        return False, "status"
    true = stacked_satisfiable(inst)
    if raw["status"] == "unsat":
        return (not true, "unsat but a codeword exists" if true else "ok")
    if not true:
        return False, "sat but no global codeword"
    blocks = raw.get("blocks")
    if not isinstance(blocks, dict):
        return False, "blocks missing"
    try:
        assignment = {n: [int(x) for x in blocks[n]] for n in inst["blocks"]}
    except Exception:
        return False, "blocks"
    if not _assignment_ok(inst, assignment):
        return False, "parity or glue failed"
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
    p = int(inst["modulus"])
    blocks = {}
    for name, spec in inst["blocks"].items():
        vec = [0] * spec["length"]
        if spec["length"] == 2 and spec["H"] == [[1, 1]]:
            vec = [1, (p - 1) % p]
        blocks[name] = vec
    return {"status": "sat", "blocks": blocks}


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
            "explicit_expand",
            generate_instance(depth=max(depth, 2), regime=regime, representation=REVEALED, seed=seed),
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
