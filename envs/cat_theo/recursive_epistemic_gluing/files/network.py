"""Recursive epistemic gluing: nested finite Kripke frames and cell bundles.

Queries use the usual modal semantics for K_a. A bundle is a choice of local
information cells, one per agent; it is possible iff those cells have a common
world. The independent checker evaluates formulas on the product of nested
frames; a second strategy enumerates the flattened global model.
"""
from __future__ import annotations

import copy
import itertools
import random
from typing import Any, Callable, Mapping, Optional


TREE = "tree"
CYCLIC_SAT = "cyclic_sat"
CYCLIC_UNSAT = "cyclic_unsat"
TRANSPARENT = "transparent"
OPAQUE = "opaque"
PUBLIC_KEYS = ("agents", "frames", "levels", "actual", "query", "bundle")
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "order_heldout",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. This is not evidence of unsatisfiability."""


def public_model(model: Mapping[str, Any]) -> dict[str, Any]:
    return {key: model[key] for key in PUBLIC_KEYS}


def _tokens(rng: random.Random, n: int, used: set[str]) -> list[str]:
    out = []
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while len(out) < n:
        tok = "".join(rng.choice(alphabet) for _ in range(5))
        if tok not in used:
            used.add(tok)
            out.append(tok)
    return out


def _classes(indist: list) -> dict[str, set[str]]:
    cell = {}
    for block in indist:
        block_set = {str(x) for x in block}
        for w in block_set:
            cell[w] = set(block_set)
    return cell


def generate_model(
    *,
    depth: int,
    regime: str,
    opacity: str,
    order: int,
    seed: int,
) -> dict[str, Any]:
    if depth < 1 or order < 0:
        raise ValueError("depth/order")
    rng = random.Random(seed)
    used: set[str] = set()

    def names(n: int, fallback: list[str]) -> list[str]:
        if opacity == TRANSPARENT:
            return list(fallback)
        return _tokens(rng, n, used)

    agents = ["ann", "bob"]
    outer_worlds = names(3, ["w0", "w1", "w2"])
    inner_worlds = names(2, ["u0", "u1"])
    w0, w1, w2 = outer_worlds
    u0, u1 = inner_worlds

    outer = {
        "worlds": outer_worlds,
        "atoms": {"p": [w0]},
        "indist": {
            "ann": [[w0, w1], [w2]],
            "bob": [[w0], [w1, w2]],
        },
    }
    inner = {
        "worlds": inner_worlds,
        "atoms": {"q": [u0]},
        "indist": {
            "ann": [[u0], [u1]],
            "bob": [[u0, u1]],
        },
    }
    frames = {"outer": outer, "inner": inner}
    levels = ["outer"] + ["inner"] * (depth - 1)
    actual = [w0] + [u0] * (depth - 1)

    if order <= 0:
        query: Any = "p"
    elif order == 1:
        query = ["K", "ann", "p"]
    else:
        query = ["K", "ann", ["K", "bob", "q" if depth > 1 else "p"]]

    if regime == CYCLIC_UNSAT:
        bundle = {"ann": w2, "bob": w0}
    elif regime == TREE:
        bundle = None
    else:
        bundle = {"ann": w0, "bob": w1}

    return {
        "agents": agents,
        "frames": frames,
        "levels": levels,
        "actual": actual,
        "query": query,
        "bundle": bundle,
        "meta": {"regime": regime, "opacity": opacity, "order": order, "depth": depth},
    }


def relabel_model(model: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    used: set[str] = set()
    maps: dict[str, dict[str, str]] = {}
    frames = {}
    for name, frame in model["frames"].items():
        mapping = {old: _tokens(rng, 1, used)[0] for old in frame["worlds"]}
        maps[name] = mapping

        def m(world: str, _mapping=mapping) -> str:
            return _mapping[world]

        frames[name] = {
            "worlds": [m(w) for w in frame["worlds"]],
            "atoms": {atom: [m(w) for w in worlds] for atom, worlds in frame["atoms"].items()},
            "indist": {
                agent: [[m(w) for w in block] for block in blocks]
                for agent, blocks in frame["indist"].items()
            },
        }
    actual = []
    for world, level in zip(model["actual"], model["levels"]):
        actual.append(maps[level][world])
    bundle = None
    if model.get("bundle"):
        bundle = {}
        root_level = model["levels"][0]
        for agent, world in model["bundle"].items():
            bundle[agent] = maps[root_level][world]
    return {
        "agents": list(model["agents"]),
        "frames": frames,
        "levels": list(model["levels"]),
        "actual": actual,
        "query": copy.deepcopy(model["query"]),
        "bundle": bundle,
        "meta": dict(model.get("meta") or {}),
    }


def example_visible_model() -> dict[str, Any]:
    return {
        "agents": ["ann", "bob"],
        "frames": {
            "leaf": {
                "worlds": ["here"],
                "atoms": {"p": ["here"]},
                "indist": {"ann": [["here"]], "bob": [["here"]]},
            }
        },
        "levels": ["leaf"],
        "actual": ["here"],
        "query": "p",
        "bundle": None,
    }


def all_chains(model: Mapping[str, Any]) -> list[tuple[str, ...]]:
    levels = model["levels"]
    frames = model["frames"]
    axes = [list(frames[level]["worlds"]) for level in levels]
    return list(itertools.product(*axes))


def related(model: Mapping[str, Any], agent: str, chain: tuple[str, ...], other: tuple[str, ...]) -> bool:
    frames = model["frames"]
    levels = model["levels"]
    for world, other_world, level in zip(chain, other, levels):
        cells = _classes(frames[level]["indist"][agent])
        if other_world not in cells.get(world, {world}):
            return False
    return True


def atom_at(model: Mapping[str, Any], atom: str, chain: tuple[str, ...]) -> bool:
    frames = model["frames"]
    levels = model["levels"]
    for world, level in zip(chain, levels):
        holds = frames[level]["atoms"].get(atom, [])
        if world in holds:
            return True
    return False


def eval_formula(model: Mapping[str, Any], formula: Any, chain: tuple[str, ...], budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0:
        raise OracleBudgetExceeded("epistemic oracle exceeded step budget; refusing to call this unsat")
    if isinstance(formula, str):
        return atom_at(model, formula, chain)
    if not isinstance(formula, list) or not formula:
        raise ValueError("bad formula")
    head = formula[0]
    if head == "not":
        return not eval_formula(model, formula[1], chain, budget)
    if head == "and":
        return eval_formula(model, formula[1], chain, budget) and eval_formula(
            model, formula[2], chain, budget
        )
    if head == "K":
        agent = formula[1]
        body = formula[2]
        for other in all_chains(model):
            if related(model, agent, chain, other):
                if not eval_formula(model, body, other, budget):
                    return False
        return True
    raise ValueError(f"unknown connective {head}")


def flatten_model(model: Mapping[str, Any]) -> dict[str, Any]:
    """Second checker: explicit global worlds = nested chains."""
    chains = all_chains(model)
    labels = [",".join(chain) for chain in chains]
    index = {chain: lab for chain, lab in zip(chains, labels)}
    atoms: dict[str, list[str]] = {}
    for chain, lab in zip(chains, labels):
        for level in model["levels"]:
            for atom, worlds in model["frames"][level]["atoms"].items():
                atoms.setdefault(atom, [])
        for atom in atoms:
            if atom_at(model, atom, chain):
                atoms[atom].append(lab)
    indist = {agent: [] for agent in model["agents"]}
    for agent in model["agents"]:
        remaining = set(chains)
        while remaining:
            seed = remaining.pop()
            block = {seed}
            for other in list(remaining):
                if related(model, agent, seed, other):
                    block.add(other)
                    remaining.remove(other)
            indist[agent].append([index[ch] for ch in block])
    actual = index[tuple(model["actual"])]
    return {
        "agents": list(model["agents"]),
        "frames": {
            "flat": {
                "worlds": labels,
                "atoms": atoms,
                "indist": indist,
            }
        },
        "levels": ["flat"],
        "actual": [actual],
        "query": copy.deepcopy(model["query"]),
        "bundle": None,
    }


def query_value(model: Mapping[str, Any]) -> bool:
    chain = tuple(model["actual"])
    return eval_formula(model, model["query"], chain, [50_000])


def bundle_possible(model: Mapping[str, Any]) -> Optional[bool]:
    bundle = model.get("bundle")
    if not bundle:
        return None
    root = model["levels"][0]
    frame = model["frames"][root]
    cells = []
    for agent, world in bundle.items():
        cls = _classes(frame["indist"][agent])
        cells.append(cls.get(str(world), {str(world)}))
    if not cells:
        return True
    inter = set(cells[0])
    for cell in cells[1:]:
        inter &= cell
    return bool(inter)


def reference_certificate(model: Mapping[str, Any]) -> dict[str, Any]:
    value = query_value(model)
    possible = bundle_possible(model)
    cert = {"query_value": bool(value)}
    if possible is not None:
        cert["bundle_possible"] = bool(possible)
    return cert


def verify_certificate(model: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    if not isinstance(raw, dict):
        return False, "not a dict"
    if "query_value" not in raw:
        return False, "query_value missing"
    true = reference_certificate(model)
    if bool(raw["query_value"]) != bool(true["query_value"]):
        return False, "query_value mismatch"
    if "bundle_possible" in true:
        if "bundle_possible" not in raw:
            return False, "bundle_possible missing"
        if bool(raw["bundle_possible"]) != bool(true["bundle_possible"]):
            return False, "bundle_possible mismatch"
    return True, "ok"


def cross_check_flat(model: Mapping[str, Any]) -> bool:
    flat = flatten_model(model)
    return query_value(flat) == query_value(model)


def arm_reference(model: Mapping[str, Any]) -> dict[str, Any]:
    return reference_certificate(model)


def arm_actual_facts(model: Mapping[str, Any]) -> dict[str, Any]:
    """Baseline analogue: evaluate atoms at the actual chain, treat K as identity."""

    def peel(formula):
        if isinstance(formula, str):
            return atom_at(model, formula, tuple(model["actual"]))
        if isinstance(formula, list) and formula and formula[0] == "not":
            return not peel(formula[1])
        if isinstance(formula, list) and formula and formula[0] == "and":
            return peel(formula[1]) and peel(formula[2])
        if isinstance(formula, list) and formula and formula[0] == "K":
            return peel(formula[2])
        return False

    cert = {"query_value": bool(peel(model["query"]))}
    if model.get("bundle") is not None:
        cert["bundle_possible"] = True
    return cert


def evaluate_solver(solve_fn: Callable, model: dict[str, Any]) -> bool:
    try:
        raw = solve_fn(copy.deepcopy(public_model(model)))
    except Exception:
        return False
    ok, _ = verify_certificate(model, raw)
    return ok


def build_grade_models(
    *, depth: int, regime: str, opacity: str, order: int, seed: int
) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_model(
        depth=depth, regime=regime, opacity=opacity, order=order, seed=seed
    )
    return [
        ("local_visible", example_visible_model()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_model(
                depth=max(depth, 1),
                regime=CYCLIC_SAT,
                opacity=opacity,
                order=max(order, 1),
                seed=seed + 11,
            ),
        ),
        (
            "assembled_unsat",
            generate_model(
                depth=max(depth, 1),
                regime=CYCLIC_UNSAT,
                opacity=opacity,
                order=max(order, 1),
                seed=seed + 13,
            ),
        ),
        ("opaque_twin", relabel_model(configured, seed + 99)),
        (
            "order_heldout",
            generate_model(
                depth=max(depth, 2),
                regime=regime if regime != TREE else CYCLIC_SAT,
                opacity=opacity,
                order=2,
                seed=seed + 17,
            ),
        ),
    ]


def grade_solver(
    solve_fn: Callable, *, depth: int, regime: str, opacity: str, order: int, seed: int
) -> dict[str, bool]:
    items = build_grade_models(
        depth=depth, regime=regime, opacity=opacity, order=order, seed=seed
    )
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, model in items:
        checks[name] = evaluate_solver(solve_fn, model)
    configured = named["configured"]
    try:
        pub = public_model(configured)
        first = solve_fn(copy.deepcopy(pub))
        second = solve_fn(copy.deepcopy(pub))
        ok, _ = verify_certificate(configured, first)
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks
