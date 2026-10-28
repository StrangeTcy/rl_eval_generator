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
    "abstraction",
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
    "quotient_positive",
    "quotient_counterfactual",
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
    # Equal-spin observations alone are invariant under swapping labels. Add an
    # asymmetric probe so inferred presentation is identifiable rather than a
    # hidden, unverifiable flag.
    probe = [[1, 2], [3, 4]]
    observed_probe = [[0, 0], [0, 0]]
    for L in SPINS:
        for R in SPINS:
            observed_probe[label_perm[L]][label_perm[R]] = probe[L][R]
    calibration = {
        "spin_pairs": [[0, 0], [1, 1]],
        "probe_table": probe,
        "observed_probe_table": observed_probe,
    }
    return {
        "abstraction": LumpingTask().instance(requested, seed, int(regime == REC_COMP)),
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
    foil = copy.deepcopy(inst)
    foil["label_perm"].reverse()
    observed = foil["calibration"]["observed_probe_table"]
    observed.reverse()
    observed[0].reverse()
    observed[1].reverse()
    foil["abstraction"] = LumpingTask().relabel(inst["abstraction"], seed)
    return foil


def example_visible_instance() -> dict[str, Any]:
    return generate_instance(depth=1, regime=DIRECT, representation=REVEALED, seed=0)


def reference_certificate(inst: Mapping[str, Any]) -> dict[str, Any]:
    if inst.get("label_perm") is None:
        inst = copy.deepcopy(inst)
        probe = tuple(map(tuple, inst["calibration"]["probe_table"]))
        observed = tuple(map(tuple, inst["calibration"]["observed_probe_table"]))
        inst["label_perm"] = (0, 1) if probe == observed else (1, 0)
    table, fixed = true_table_and_fixed(inst)
    result: dict[str, Any] = {"table": table, "fixed": bool(fixed)}
    if inst.get("representation") == INFERRED:
        result["label_perm"] = copy.deepcopy(inst["label_perm"])
    result["abstraction"] = LumpingTask().solve(inst["abstraction"])
    return result


def verify_certificate(inst: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, dict):
        return False, "not a dict"
    if "table" not in raw or "fixed" not in raw:
        return False, "table/fixed missing"
    if type(raw["fixed"]) is not bool:
        return False, "fixed must be a bool"
    if not LumpingTask().verify(inst["abstraction"], raw.get("abstraction")):
        return 0, "abstraction or composition prediction failed"
    candidate = inst
    if inst.get("representation") == INFERRED:
        submitted = raw.get("label_perm") if isinstance(raw, dict) else None
        if submitted is None or tuple(sorted(submitted)) != (0, 1):
            return False, "inferred representation requires label_perm"
        observed = inst["calibration"]["observed_probe_table"]
        probe = inst["calibration"]["probe_table"]
        expected = [[0, 0], [0, 0]]
        for L in SPINS:
            for R in SPINS:
                expected[submitted[L]][submitted[R]] = probe[L][R]
        if tuple(map(tuple, expected)) != tuple(map(tuple, observed)):
            return False, "label_perm disagrees with calibration"
        candidate = copy.deepcopy(inst)
        candidate["label_perm"] = list(submitted)
    true_table, true_fixed = true_table_and_fixed(candidate)
    try:
        got = tuple(map(tuple, raw["table"]))
    except Exception:
        return False, "table"
    if got != tuple(map(tuple, true_table)):
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
    probe = tuple(map(tuple, inst["calibration"]["probe_table"]))
    observed = tuple(map(tuple, inst["calibration"]["observed_probe_table"]))
    return {"table": table, "fixed": True,
            "label_perm": (0, 1) if probe == observed else (1, 0),
            "abstraction": LumpingTask().solve(inst["abstraction"])}


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
        ("quotient_positive", LumpingTask().intervention(configured, seed + 31, 0)),
        ("quotient_counterfactual", LumpingTask().intervention(configured, seed + 31, 1)),
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



class LumpingTask:
    """Infer a two-state quotient of six- or ten-state observed dynamics.

    The hidden partition is not supplied. Both transition tables must commute
    with a proposed quotient. One microscopic edge can destroy its existence.
    """

    def size(self, values):
        if not values:
            return 0
        return 1 + self.size(values[1:])

    def rename(self, table, perm, index=0):
        if index == self.size(table):
            return ()
        return (perm[table[perm.index(index)]],) + self.rename(table, perm, index + 1)

    def instance(self, depth, seed, broken=0):
        width = 3 + 2 * (seed % 2)
        a, b = self.dynamics(width, broken)
        task = ((a, b), ((0, 0), (width, 1)),
                ((0, (0, 1) * depth + (0,)), (2 * width - 1, (1, 0) * depth)))
        return self.relabel(task, seed)

    def dynamics(self, width, broken, position=0):
        if position == 2 * width:
            return (), ()
        a, b = self.dynamics(width, broken, position + 1)
        target = width if broken and position == 2 * width - 1 else (position + width) % (2 * width)
        return (target,) + a, ((position + 1) % width,) + b

    def relabel(self, task, seed):
        tables, anchors, queries = task
        width = self.size(tables[0])
        perm = tuple(random.Random(seed).sample(range(width), width))
        return (
            (self.rename(tables[0], perm), self.rename(tables[1], perm)),
            ((perm[anchors[0][0]], anchors[0][1]), (perm[anchors[1][0]], anchors[1][1])),
            ((perm[queries[0][0]], queries[0][1]), (perm[queries[1][0]], queries[1][1])),
        )

    def partition(self, code, remaining=6):
        if remaining == 0:
            return ()
        return (code % 2,) + self.partition(code // 2, remaining - 1)

    def compatibility(self, tables, partition, effective, index=0):
        if index == self.size(partition):
            return 1
        label = partition[index]
        if (partition[tables[0][index]] != effective[0][label]
                or partition[tables[1][index]] != effective[1][label]):
            return 0
        return self.compatibility(tables, partition, effective, index + 1)

    def predict(self, effective, state, word):
        if not word:
            return state
        return self.predict(effective, effective[word[0]][state], word[1:])

    def candidate(self, task, code):
        tables, anchors, queries = task
        p = self.partition(code, self.size(tables[0]))
        if p[anchors[0][0]] != anchors[0][1] or p[anchors[1][0]] != anchors[1][1]:
            return ("obstruction",)
        zero, one = p.index(0), p.index(1)
        effective = ((p[tables[0][zero]], p[tables[0][one]]), (p[tables[1][zero]], p[tables[1][one]]))
        if not self.compatibility(tables, p, effective):
            return ("obstruction",)
        predictions = (self.predict(effective, p[queries[0][0]], queries[0][1]),
                       self.predict(effective, p[queries[1][0]], queries[1][1]))
        return "quotient", p, effective, predictions

    def search(self, task, start, span):
        if span == 1:
            return self.candidate(task, start)
        first = self.search(task, start, span // 2)
        if first[0] == "quotient":
            return first
        return self.search(task, start + span // 2, span // 2)

    def solve(self, task):
        width = self.size(task[0][0])
        if width > 12:
            raise OracleBudgetExceeded("quotient enumeration supports at most twelve microstates")
        return self.search(task, 0, 2 ** width)

    def microscopic_prediction(self, task, query):
        """Direct-state rival: predicts observations without finding a quotient."""
        tables, anchors, queries = task
        state, word = query
        return self.predict(tables, state, word)

    def intervention(self, inst, seed, broken):
        foil = copy.deepcopy(inst)
        foil["abstraction"] = self.instance(inst["depth"], seed, broken)
        return foil

    def verify(self, task, raw):
        try:
            if tuple(raw) == ("obstruction",):
                return int(self.solve(task) == ("obstruction",))
            status, partition, effective, predictions = raw
            p = tuple(partition)
            tables, anchors, queries = task
            if status != "quotient" or p.count(0) + p.count(1) != self.size(tables[0]):
                return 0
            zero, one = effective
            zero_a, one_a = zero
            zero_b, one_b = one
            if set((zero_a, one_a, zero_b, one_b)).difference((0, 1)):
                return 0
            if p[anchors[0][0]] != anchors[0][1] or p[anchors[1][0]] != anchors[1][1]:
                return 0
            if not self.compatibility(tables, p, effective):
                return 0
            expected = (self.predict(effective, p[queries[0][0]], queries[0][1]),
                        self.predict(effective, p[queries[1][0]], queries[1][1]))
            return int(tuple(predictions) == expected)
        except (IndexError, TypeError, ValueError):
            return 0
