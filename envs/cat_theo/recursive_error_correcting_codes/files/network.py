"""Recursive linear codes over a prime field.

Each block has a parity-check matrix over F_p. A child contributes symbols to
its parent through a coordinate permutation (and optional nonzero scale). The
oracle multiplies matrices by vectors in F_p; it does not call a generic CSP
solver. Local kernels may be nonempty while the stacked overlap system is not.
"""
from __future__ import annotations

import copy
import random
from operator import index
from typing import Any, Callable, Mapping, Optional


DIRECT = "direct"
RECURSIVE = "recursive"
FLAT = "flat"
REC_COMP = "recursive_composition"
REVEALED = "revealed"
INFERRED = "inferred"
PUBLIC_KEYS = (
    "identification",
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
    "parent_positive",
    "parent_counterfactual",
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
        probes = words[:2]
        calibration[name] = {
            "codewords": probes,
            # The observed coordinates are the evidence from which an inferred
            # presentation must recover the hidden permutation.  The old
            # calibration exposed only unpermuted words, so inferred mode was
            # not an identifiable task.
            "observed": [_apply_perm(vec, perms[name]) for vec in probes],
        }
    return {
        "identification": CodePresentation().identification(seed, seed % 2),
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
    p = int(inst["modulus"])
    scale = 2 + seed % (p - 2)
    foil = copy.deepcopy(inst)
    foil["parent_check"]["rhs"] = (scale * foil["parent_check"]["rhs"]) % p
    return CodePresentation().transform(foil, tuple(foil["blocks"]), scale)


def example_visible_instance() -> dict[str, Any]:
    return generate_instance(depth=1, regime=DIRECT, representation=REVEALED, seed=0)


def reference_certificate(inst: Mapping[str, Any]) -> dict[str, Any]:
    return CodeLinearSystem().certificate(inst)


def enumeration_certificate(inst):
    """Bounded exhaustive rival; independent of field elimination."""
    if inst.get("perms") is None:
        inst = CodePresentation().recover(inst)
    p = int(inst["modulus"])
    names = list(inst["blocks"])
    lengths = {n: inst["blocks"][n]["length"] for n in names}
    from itertools import product

    dims = [lengths[n] for n in names]
    coords = [range(p) for _ in range(sum(dims))]
    remaining = 80000
    for vec in product(*coords):
        remaining -= 1
        if remaining < 0:
            raise OracleBudgetExceeded("reference enumeration exhausted; no unsat conclusion")
        assignment: dict[str, list[int]] = {}
        k = 0
        for n in names:
            L = lengths[n]
            assignment[n] = list(vec[k : k + L])
            k += L
        foil = copy.deepcopy(inst)
        # reuse stacked check on a singleton by injecting
        if _assignment_ok(inst, assignment):
            result: dict[str, Any] = {"status": "sat", "blocks": assignment}
            if inst.get("representation") == INFERRED:
                result["perms"] = copy.deepcopy(inst["perms"])
            result["identification"] = CodePresentation().invariants(inst["identification"])
            return result
    return {"status": "unsat", "perms": copy.deepcopy(inst["perms"]),
            "identification": CodePresentation().invariants(inst["identification"])}


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
    if not CodePresentation().verify(inst["identification"], raw.get("identification")):
        return 0, "calibration ambiguity or corruption invariant failed"
    candidate = inst
    if inst.get("representation") == INFERRED:
        submitted_perms = raw.get("perms") if isinstance(raw, dict) else None
        if not isinstance(submitted_perms, dict):
            return False, "inferred representation requires perms"
        candidate = copy.deepcopy(inst)
        candidate["perms"] = {}
        for name, spec in inst["blocks"].items():
            perm = submitted_perms.get(name)
            try:
                perm = tuple(map(index, perm))
            except TypeError:
                return 0, "permutation coordinates must be integers"
            if perm is None or tuple(sorted(perm)) != tuple(range(int(spec["length"]))):
                return False, f"invalid permutation for {name}"
            calibration = inst["calibration"][name]
            observed = calibration["observed"]
            for source, expected in zip(calibration["codewords"], observed):
                if _apply_perm(list(source), perm) != list(expected):
                    return False, f"permutation for {name} disagrees with calibration"
            candidate["perms"][name] = list(perm)
    if raw["status"] == "unsat":
        return CodeLinearSystem().solution(candidate) is None, "checked linear system"
    blocks = raw.get("blocks")
    if not isinstance(blocks, dict):
        return False, "blocks missing"
    try:
        assignment = CodePresentation().coordinates(blocks, tuple(inst["blocks"]), {})
    except Exception:
        return False, "blocks"
    if not CodePresentation().assignment_shape(candidate, assignment, tuple(candidate["blocks"])):
        return 0, "coordinate count or field value is invalid"
    if not _assignment_ok(candidate, assignment):
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
    if inst.get("perms") is None:
        inst = CodePresentation().recover(inst)
    p = int(inst["modulus"])
    blocks = {}
    for name, spec in inst["blocks"].items():
        vec = [0] * spec["length"]
        if spec["length"] == 2 and spec["H"] == [[1, 1]]:
            vec = [1, (p - 1) % p]
        blocks[name] = vec
    return {"status": "sat", "blocks": blocks, "perms": copy.deepcopy(inst["perms"]),
            "identification": CodePresentation().invariants(inst["identification"])}


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
        ("parent_positive", CodePresentation().parent_control(max(2, depth), representation, seed + 31, 0)),
        ("parent_counterfactual", CodePresentation().parent_control(max(2, depth), representation, seed + 31, 1)),
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



class CodePresentation:
    """Coordinate and unit changes, calibration ambiguity, and syndrome controls."""

    def rows(self, rows, scale, p, swap=0):
        if not rows:
            return ()
        row = tuple(rows[0])
        transformed = ((scale * row[1]) % p, (scale * row[0]) % p) if swap else (
            (scale * row[0]) % p, (scale * row[1]) % p)
        return (transformed,) + self.rows(rows[1:], scale, p, swap)

    def transform(self, foil, names, scale):
        if not names:
            return foil
        name = names[0]
        p = foil["modulus"]
        spec = foil["blocks"][name]
        spec["H"] = self.rows(spec["H"], pow(scale, -1, p), p, 1)
        perm = foil["perms"][name]
        foil["perms"][name] = (1 - perm[0], 1 - perm[1])
        calibration = foil["calibration"][name]
        calibration["codewords"] = self.rows(calibration["codewords"], scale, p, 1)
        calibration["observed"] = self.rows(calibration["observed"], scale, p)
        return self.transform(foil, names[1:], scale)

    def recover(self, inst, names=None):
        if names is None:
            inst = copy.deepcopy(inst)
            inst["perms"] = inst["calibration"].copy()
            return self.recover(inst, tuple(inst["blocks"]))
        if not names:
            return inst
        name = names[0]
        c = inst["calibration"][name]
        source, observed = tuple(c["codewords"][1]), tuple(c["observed"][1])
        inst["perms"][name] = (0, 1) if source == observed else (1, 0)
        return self.recover(inst, names[1:])

    def observe(self, word, perm):
        return word[perm[0]], word[perm[1]], word[perm[2]]

    def identification(self, seed, extra=0):
        choices = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
        perm = choices[seed % 6]
        probes = ((1, 1, 3), (0, 1, 4)) if extra else ((1, 1, 3),)
        observed = (self.observe(probes[0], perm),)
        if extra:
            observed += (self.observe(probes[1], perm),)
        received = self.observe((2 + seed % 4, 1, 3), perm)
        return 5, probes, observed, received

    def matches(self, probes, observed, perm):
        if not probes:
            return 1
        if self.observe(probes[0], perm) != tuple(observed[0]):
            return 0
        return self.matches(probes[1:], observed[1:], perm)

    def admissible(self, probes, observed, choices):
        if not choices:
            return ()
        tail = self.admissible(probes, observed, choices[1:])
        return (choices[0],) + tail if self.matches(probes, observed, choices[0]) else tail

    def invariants(self, task):
        p, probes, observed, received = task
        choices = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
        admissible = self.admissible(probes, observed, choices)
        syndrome = sum(received) % p
        x, y, z = received
        corrections = (((x - syndrome) % p, y % p, z % p),
                       (x % p, (y - syndrome) % p, z % p),
                       (x % p, y % p, (z - syndrome) % p))
        return admissible, syndrome, corrections

    def verify(self, task, raw):
        try:
            choices, syndrome, corrections = raw
            a, s, c = self.invariants(task)
            return int(set(map(tuple, choices)) == set(a) and syndrome == s
                       and set(map(tuple, corrections)) == set(c))
        except (TypeError, ValueError):
            return 0

    def assignment_shape(self, inst, assignment, names):
        if not names:
            return 1
        name = names[0]
        word = tuple(assignment[name])
        if word[inst["blocks"][name]["length"]:] or not word:
            return 0
        if self.width(word) != inst["blocks"][name]["length"]:
            return 0
        try:
            tuple(map(index, word))
        except TypeError:
            return 0
        if min(word) < 0 or max(word) >= inst["modulus"]:
            return 0
        return self.assignment_shape(inst, assignment, names[1:])

    def width(self, sequence):
        if not sequence:
            return 0
        return 1 + self.width(sequence[1:])

    def coordinates(self, blocks, names, result):
        if not names:
            return result
        result[names[0]] = tuple(map(index, blocks[names[0]]))
        return self.coordinates(blocks, names[1:], result)

    def parent_control(self, depth, representation, seed, rhs):
        inst = generate_instance(depth=depth, regime=RECURSIVE,
                                 representation=representation, seed=seed)
        inst["parent_check"]["rhs"] = rhs
        return inst


class CodeLinearSystem:
    """Field elimination on all local checks, presented overlaps, and RHS.

    The exhaustive stacked_satisfiable/enumeration_certificate routines are
    retained as separately implemented small-instance rivals.
    """

    def variables(self, inst, names, coordinate=0):
        if not names:
            return ()
        name = names[0]
        if coordinate == inst["blocks"][name]["length"]:
            return self.variables(inst, names[1:])
        return ((name, coordinate),) + self.variables(inst, names, coordinate + 1)

    def terms(self, coordinates, coefficients):
        if not coordinates:
            return ()
        return ((tuple(coordinates[0]), coefficients[0]),) + self.terms(coordinates[1:], coefficients[1:])

    def coefficient(self, variable, terms):
        if not terms:
            return 0
        value = terms[0][1] if variable == terms[0][0] else 0
        return value + self.coefficient(variable, terms[1:])

    def row(self, variables, terms, p):
        if not variables:
            return ()
        return (self.coefficient(variables[0], terms) % p,) + self.row(variables[1:], terms, p)

    def local_rows(self, inst, variables, names, checks=None):
        if not names:
            return ()
        name = names[0]
        if checks is None:
            checks = inst["blocks"][name]["H"]
        if not checks:
            return self.local_rows(inst, variables, names[1:])
        local = self.variables(inst, (name,))
        row = self.row(variables, self.terms(local, checks[0]), inst["modulus"])
        return (row + (0,),) + self.local_rows(inst, variables, names, checks[1:])

    def overlap_rows(self, inst, variables, edges):
        if not edges:
            return ()
        edge = edges[0]
        a, i = edge["left"]
        b, j = edge["right"]
        terms = (((a, inst["perms"][a][i]), 1), ((b, inst["perms"][b][j]), -edge["scale"]))
        row = self.row(variables, terms, inst["modulus"])
        return (row + (0,),) + self.overlap_rows(inst, variables, edges[1:])

    def presented(self, inst, coordinates):
        if not coordinates:
            return ()
        name, coordinate = coordinates[0]
        return ((name, inst["perms"][name][coordinate]),) + self.presented(inst, coordinates[1:])

    def pivot(self, rows):
        if not rows:
            return None, ()
        if rows[0][0]:
            return rows[0], rows[1:]
        pivot, rest = self.pivot(rows[1:])
        return pivot, (rows[0],) + rest

    def subtract(self, row, pivot, factor, p):
        if not row:
            return ()
        return ((row[0] - factor * pivot[0]) % p,) + self.subtract(row[1:], pivot[1:], factor, p)

    def eliminate(self, rows, pivot, p):
        if not rows:
            return ()
        factor = rows[0][0] * pow(pivot[0], -1, p) % p
        reduced = self.subtract(rows[0], pivot, factor, p)[1:]
        return (reduced,) + self.eliminate(rows[1:], pivot, p)

    def drop(self, rows):
        if not rows:
            return ()
        return (rows[0][1:],) + self.drop(rows[1:])

    def dot(self, a, b):
        if not a:
            return 0
        return a[0] * b[0] + self.dot(a[1:], b[1:])

    def consistent(self, rows, p):
        if not rows:
            return 1
        return self.consistent(rows[1:], p) if rows[0][0] % p == 0 else 0

    def solve(self, rows, variables, p):
        if not variables:
            return () if self.consistent(rows, p) else None
        pivot, rest = self.pivot(rows)
        if pivot is None:
            tail = self.solve(self.drop(rows), variables[1:], p)
            return None if tail is None else (0,) + tail
        tail = self.solve(self.eliminate(rest, pivot, p), variables[1:], p)
        if tail is None:
            return None
        value = (pivot[-1] - self.dot(pivot[1:-1], tail)) * pow(pivot[0], -1, p) % p
        return (value,) + tail

    def solution(self, inst):
        variables = self.variables(inst, tuple(inst["blocks"]))
        parent = inst["parent_check"]
        terms = self.terms(self.presented(inst, parent["vars"]), parent["row"])
        final = self.row(variables, terms, inst["modulus"]) + (parent["rhs"] % inst["modulus"],)
        rows = self.local_rows(inst, variables, tuple(inst["blocks"]))
        rows += self.overlap_rows(inst, variables, inst["glues"]) + (final,)
        return self.solve(rows, variables, inst["modulus"])

    def assignment(self, inst, names, values, result):
        if not names:
            return result
        name = names[0]
        width = inst["blocks"][name]["length"]
        result[name] = values[:width]
        return self.assignment(inst, names[1:], values[width:], result)

    def certificate(self, inst):
        if inst.get("perms") is None:
            inst = CodePresentation().recover(inst)
        values = self.solution(inst)
        cert = {"status": "unsat" if values is None else "sat",
                "perms": copy.deepcopy(inst["perms"]),
                "identification": CodePresentation().invariants(inst["identification"])}
        if values is not None:
            cert["blocks"] = self.assignment(inst, tuple(inst["blocks"]), values, {})
        return cert
