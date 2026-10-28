"""Recursive epistemic gluing: nested finite Kripke frames and cell bundles.

Queries use the usual modal semantics for K_a. A bundle is a choice of local
information cells, one per agent; it is possible iff those cells have a common
world. Nested bundles are the same check on an inner frame. The independent
checker evaluates formulas on the product of nested frames; a second strategy
enumerates the flattened global model. The judge does not call the reference
certificate helper.
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
PUBLIC_KEYS = ("agents", "frames", "levels", "actual", "query", "bundle", "nested_bundle", "knowledge_probe")
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "order_heldout",
    "neg_deep",
    "neg_recursive",
    "modal_positive",
    "modal_counterfactual",
    "deterministic",
)

POS_PLAIN = "POS-plain"
POS_RECURSIVE = "POS-recursive"
NEG_LOCAL = "NEG-local"
NEG_PAIRWISE = "NEG-pairwise"
NEG_DEEP = "NEG-deep"
NEG_RECURSIVE = "NEG-recursive"
INSTANCE_CLASSES = (
    POS_PLAIN,
    POS_RECURSIVE,
    NEG_LOCAL,
    NEG_PAIRWISE,
    NEG_DEEP,
    NEG_RECURSIVE,
)
DEV_SEEDS = range(0, 30)
HELD_OUT_SEEDS = range(10_000, 10_030)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. This is not evidence of unsatisfiability."""


def public_model(model: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    for key in PUBLIC_KEYS:
        if key == "nested_bundle" or key == "knowledge_probe":
            out[key] = model.get(key)
        else:
            out[key] = model[key]
    return out


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


def cell_of(frame: Mapping[str, Any], agent: str, world: Any) -> set[str]:
    """Indistinguishability block containing `world`, or empty if locally illegal."""
    world_s = str(world)
    worlds = {str(w) for w in frame["worlds"]}
    if world_s not in worlds:
        return set()
    blocks = frame["indist"][agent]
    for block in blocks:
        as_set = {str(x) for x in block}
        if world_s in as_set:
            return as_set
    return set()


def cells_for_reports(frame: Mapping[str, Any], reports: Mapping[str, Any]) -> list[set[str]]:
    return [cell_of(frame, agent, world) for agent, world in reports.items()]


def kwise_nonempty(cells: list[set[str]], k: int) -> bool:
    if k <= 0:
        return True
    if len(cells) < k:
        return True
    for group in itertools.combinations(cells, k):
        inter = set(group[0])
        for cell in group[1:]:
            inter &= cell
        if not inter:
            return False
    return True


def intersection_of(cells: list[set[str]]) -> set[str]:
    if not cells:
        return set()
    inter = set(cells[0])
    for cell in cells[1:]:
        inter &= cell
    return inter


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
    if order >= 2:
        return KnowledgeProbe().generate(depth, order, regime, opacity, seed)
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
        bundle: Optional[dict[str, str]] = {"ann": w2, "bob": w0}
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
        "nested_bundle": None,
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

    def remap_reports(reports: Optional[Mapping[str, Any]], level: str) -> Optional[dict[str, str]]:
        if not reports:
            return None
        mapping = maps[level]
        out = {}
        for agent, world in reports.items():
            world_s = str(world)
            out[agent] = mapping[world_s] if world_s in mapping else world_s
        return out

    bundle = remap_reports(model.get("bundle"), model["levels"][0])
    nested = None
    if model.get("nested_bundle") and len(model["levels"]) > 1:
        nested = remap_reports(model["nested_bundle"], model["levels"][1])
    elif model.get("nested_bundle"):
        nested = dict(model["nested_bundle"])
    return {
        "agents": list(model["agents"]),
        "frames": frames,
        "levels": list(model["levels"]),
        "actual": actual,
        "query": copy.deepcopy(model["query"]),
        "knowledge_probe": model.get("knowledge_probe"),
        "bundle": bundle,
        "nested_bundle": nested,
        "meta": dict(model.get("meta") or {}),
    }


def presentation_twin(model: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Rename worlds and reorder agent/bundle keys. Verdict must be invariant."""
    twin = relabel_model(model, seed)
    rng = random.Random(seed + 7919)
    agents = list(twin["agents"])
    rng.shuffle(agents)
    twin["agents"] = agents
    if twin.get("bundle"):
        items = list(twin["bundle"].items())
        rng.shuffle(items)
        twin["bundle"] = dict(items)
    if twin.get("nested_bundle"):
        items = list(twin["nested_bundle"].items())
        rng.shuffle(items)
        twin["nested_bundle"] = dict(items)
    return twin


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
        "nested_bundle": None,
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


def eval_formula(model: Mapping[str, Any], formula: Any, chain: tuple[str, ...], budget: list[int], cache=None) -> bool:
    if cache is None:
        cache = {}
    key = (repr(formula), chain)
    cached = cache.get(key)
    if cached is not None:
        return cached
    budget[0] -= 1
    if budget[0] < 0:
        raise OracleBudgetExceeded("epistemic oracle exceeded step budget; refusing to call this unsat")
    if isinstance(formula, str):
        value = atom_at(model, formula, chain)
        cache[key] = value
        return value
    if not formula:
        raise ValueError("bad formula")
    head = formula[0]
    if head == "not":
        value = not eval_formula(model, formula[1], chain, budget, cache)
        cache[key] = value
        return value
    if head == "and":
        value = eval_formula(model, formula[1], chain, budget, cache) and eval_formula(
            model, formula[2], chain, budget, cache
        )
        cache[key] = value
        return value
    if head == "K":
        agent = formula[1]
        body = formula[2]
        for other in all_chains(model):
            if related(model, agent, chain, other):
                if not eval_formula(model, body, other, budget, cache):
                    cache[key] = False
                    return False
        cache[key] = True
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
        "nested_bundle": None,
    }


def query_value(model: Mapping[str, Any], budget: int = 50_000) -> bool:
    chain = tuple(model["actual"])
    return eval_formula(model, model["query"], chain, [budget])


def _reports_possible(frame: Mapping[str, Any], reports: Optional[Mapping[str, Any]]) -> Optional[bool]:
    if not reports:
        return None
    cells = cells_for_reports(frame, reports)
    if any(len(cell) == 0 for cell in cells):
        return False
    return bool(intersection_of(cells))


def bundle_possible(model: Mapping[str, Any]) -> Optional[bool]:
    bundle = model.get("bundle")
    nested = model.get("nested_bundle")
    if not bundle and not nested:
        return None
    flags: list[bool] = []
    if bundle:
        root = model["levels"][0]
        outer = _reports_possible(model["frames"][root], bundle)
        flags.append(bool(outer))
    if nested:
        if len(model["levels"]) < 2:
            flags.append(False)
        else:
            inner_level = model["levels"][1]
            inner = _reports_possible(model["frames"][inner_level], nested)
            flags.append(bool(inner))
    return all(flags) if flags else None


def task_sat(model: Mapping[str, Any]) -> bool:
    if not query_value(model):
        return False
    possible = bundle_possible(model)
    if possible is None:
        return True
    return bool(possible)


def flatten_task_model(model: Mapping[str, Any]) -> dict[str, Any]:
    """Permissive inner: drop nested frames and nested reports."""
    outer = model["levels"][0]
    return {
        "agents": list(model["agents"]),
        "frames": {outer: copy.deepcopy(model["frames"][outer])},
        "levels": [outer],
        "actual": [model["actual"][0]],
        "query": copy.deepcopy(model["query"]),
        "bundle": copy.deepcopy(model.get("bundle")),
        "nested_bundle": None,
    }


def bounded_task_model(model: Mapping[str, Any], k: int) -> dict[str, Any]:
    if k <= 0:
        return flatten_task_model(model)
    n = min(len(model["levels"]), k)
    levels = list(model["levels"][:n])
    foil = {
        "agents": list(model["agents"]),
        "frames": {lev: copy.deepcopy(model["frames"][lev]) for lev in levels},
        "levels": levels,
        "actual": list(model["actual"][:n]),
        "query": copy.deepcopy(model["query"]),
        "bundle": copy.deepcopy(model.get("bundle")),
        "nested_bundle": None,
    }
    if k >= 2:
        foil["nested_bundle"] = copy.deepcopy(model.get("nested_bundle"))
    return foil


def local_ok(model: Mapping[str, Any]) -> bool:
    bundle = model.get("bundle")
    nested = model.get("nested_bundle")
    if bundle:
        root = model["frames"][model["levels"][0]]
        if any(len(c) == 0 for c in cells_for_reports(root, bundle)):
            return False
    if nested:
        if len(model["levels"]) < 2:
            return False
        inner = model["frames"][model["levels"][1]]
        if any(len(c) == 0 for c in cells_for_reports(inner, nested)):
            return False
    return True


def pairwise_ok(model: Mapping[str, Any]) -> bool:
    """Phase-0 B1: pairwise compatibility on the *outer* bundle only."""
    if not local_ok(model):
        return False
    bundle = model.get("bundle")
    if not bundle:
        return True
    cells = cells_for_reports(model["frames"][model["levels"][0]], bundle)
    return kwise_nonempty(cells, 2)


def triple_ok(model: Mapping[str, Any]) -> bool:
    bundle = model.get("bundle")
    if not bundle:
        return True
    cells = cells_for_reports(model["frames"][model["levels"][0]], bundle)
    return kwise_nonempty(cells, 3)


def joint_worlds(model: Mapping[str, Any]) -> tuple[Optional[str], Optional[str]]:
    outer_j: Optional[str] = None
    inner_j: Optional[str] = None
    bundle = model.get("bundle")
    if bundle:
        cells = cells_for_reports(model["frames"][model["levels"][0]], bundle)
        inter = intersection_of(cells)
        outer_j = sorted(inter)[0] if inter else None
    nested = model.get("nested_bundle")
    if nested and len(model["levels"]) > 1:
        cells = cells_for_reports(model["frames"][model["levels"][1]], nested)
        inter = intersection_of(cells)
        inner_j = sorted(inter)[0] if inter else None
    return outer_j, inner_j


def world_in_all_cells(frame: Mapping[str, Any], reports: Mapping[str, Any], world: Any) -> bool:
    world_s = str(world)
    if world_s not in {str(w) for w in frame["worlds"]}:
        return False
    return all(world_s in cell_of(frame, agent, named) for agent, named in reports.items())


def _require_bool(raw: Mapping[str, Any], key: str) -> tuple[Optional[bool], str]:
    """Reject truthy non-booleans. `bool("false")` is True; that is not a Boolean."""
    if key not in raw:
        return None, f"{key} missing"
    value = raw[key]
    if type(value) is not bool:
        return None, f"{key} must be a bool, got {type(value).__name__}"
    return value, ""


def reference_certificate(model: Mapping[str, Any]) -> dict[str, Any]:
    value = query_value(model)
    possible = bundle_possible(model)
    cert: dict[str, Any] = {"query_value": bool(value)}
    if model.get("bundle") is not None or model.get("nested_bundle") is not None:
        cert["bundle_possible"] = bool(possible)
        if possible:
            outer_j, inner_j = joint_worlds(model)
            if outer_j is not None:
                cert["joint_world"] = outer_j
            if inner_j is not None:
                cert["joint_inner"] = inner_j
    if model.get("knowledge_probe") is not None:
        cert["reachability"] = KnowledgeProbe().certificate(model)
    return cert


def verify_certificate(model: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    """Recompute query and bundle from the model; replay joint-world witnesses.

    Boolean fields are checked by type (`type(v) is bool`), not by truthiness.
    Trusted oracles used here: `query_value`, `flatten_model` (depth 1), and
    cell intersection via `bundle_possible` / `world_in_all_cells`. This is
    not the evaluated candidate solver.
    """
    if not isinstance(raw, dict):
        return False, "not a dict"
    claimed_q, err = _require_bool(raw, "query_value")
    if err:
        return False, err
    if model.get("knowledge_probe") is not None:
        if not KnowledgeProbe().verify(model, raw.get("reachability")):
            return 0, "modal reachability certificate failed"
    true_q = query_value(model)
    if len(model["levels"]) == 1:
        flat_q = query_value(flatten_model(model))
        if flat_q is not true_q:
            raise RuntimeError("depth-1 nested evaluator disagrees with flattened evaluator")
    if claimed_q is not true_q:
        return False, "query_value mismatch"
    has_bundle = model.get("bundle") is not None or model.get("nested_bundle") is not None
    if not has_bundle:
        return True, "ok"
    claimed_b, err = _require_bool(raw, "bundle_possible")
    if err:
        return False, err
    true_b = bundle_possible(model)
    if true_b is None:
        return False, "bundle_possible missing from the instance"
    if claimed_b is not true_b:
        return False, "bundle_possible mismatch"
    if not claimed_b:
        return True, "ok"
    bundle = model.get("bundle")
    if bundle is not None:
        joint = raw.get("joint_world")
        if joint is None:
            return False, "joint_world missing"
        if not world_in_all_cells(model["frames"][model["levels"][0]], bundle, joint):
            return False, "joint_world not in every outer cell"
    nested = model.get("nested_bundle")
    if nested is not None:
        if len(model["levels"]) < 2:
            return False, "nested_bundle without an inner frame"
        joint_inner = raw.get("joint_inner")
        if joint_inner is None:
            return False, "joint_inner missing"
        if not world_in_all_cells(model["frames"][model["levels"][1]], nested, joint_inner):
            return False, "joint_inner not in every inner cell"
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
    if model.get("bundle") is not None or model.get("nested_bundle") is not None:
        cert["bundle_possible"] = True
    return cert


def evaluate_solver(solve_fn: Callable, model: dict[str, Any]) -> bool:
    try:
        raw = solve_fn(copy.deepcopy(public_model(model)))
    except Exception:
        return False
    ok, _ = verify_certificate(model, raw)
    return ok


def _four_world_cover(*, common: bool, seed: int, opacity: str) -> dict[str, Any]:
    """Four agents. If common, all cells contain w0. If not, every 3-wise is
    nonempty and the 4-wise intersection is empty."""
    rng = random.Random(seed)
    used: set[str] = set()
    agents = ["ann", "bob", "cara", "dan"]
    if opacity == TRANSPARENT:
        worlds = ["w0", "w1", "w2", "w3"]
    else:
        worlds = _tokens(rng, 4, used)
    w0, w1, w2, w3 = worlds
    ann, bob, cara, dan = agents
    if common:
        block = [w0, w1, w2, w3]
        indist = {agent: [list(block)] for agent in agents}
        bundle = {agent: w0 for agent in agents}
    else:
        indist = {
            ann: [[w1, w2, w3], [w0]],
            bob: [[w0, w2, w3], [w1]],
            cara: [[w0, w1, w3], [w2]],
            dan: [[w0, w1, w2], [w3]],
        }
        bundle = {ann: w1, bob: w0, cara: w0, dan: w0}
    return {
        "agents": agents,
        "frames": {
            "outer": {
                "worlds": worlds,
                "atoms": {"p": [w0]},
                "indist": indist,
            }
        },
        "levels": ["outer"],
        "actual": [w0],
        "query": "p",
        "bundle": bundle,
        "nested_bundle": None,
        "meta": {"class": NEG_DEEP if not common else POS_PLAIN, "opacity": opacity, "seed": seed},
    }


def handwritten_neg_deep() -> dict[str, Any]:
    return {
        "agents": ["ann", "bob", "cara", "dan"],
        "frames": {
            "outer": {
                "worlds": ["w0", "w1", "w2", "w3"],
                "atoms": {"p": ["w0"]},
                "indist": {
                    "ann": [["w1", "w2", "w3"], ["w0"]],
                    "bob": [["w0", "w2", "w3"], ["w1"]],
                    "cara": [["w0", "w1", "w3"], ["w2"]],
                    "dan": [["w0", "w1", "w2"], ["w3"]],
                },
            }
        },
        "levels": ["outer"],
        "actual": ["w0"],
        "query": "p",
        "bundle": {"ann": "w1", "bob": "w0", "cara": "w0", "dan": "w0"},
        "nested_bundle": None,
    }


def handwritten_neg_recursive() -> dict[str, Any]:
    return {
        "agents": ["ann", "bob"],
        "frames": {
            "outer": {
                "worlds": ["w0", "w1", "w2"],
                "atoms": {"p": ["w0"]},
                "indist": {
                    "ann": [["w0", "w1"], ["w2"]],
                    "bob": [["w0"], ["w1", "w2"]],
                },
            },
            "inner": {
                "worlds": ["u0", "u1"],
                "atoms": {"q": ["u0"]},
                "indist": {
                    "ann": [["u0"], ["u1"]],
                    "bob": [["u0"], ["u1"]],
                },
            },
        },
        "levels": ["outer", "inner"],
        "actual": ["w0", "u0"],
        "query": "p",
        "bundle": {"ann": "w0", "bob": "w1"},
        "nested_bundle": {"ann": "u0", "bob": "u1"},
    }


def handwritten_pos_recursive() -> dict[str, Any]:
    return {
        "agents": ["ann", "bob"],
        "frames": {
            "outer": {
                "worlds": ["w0", "w1", "w2"],
                "atoms": {"p": ["w0"]},
                "indist": {
                    "ann": [["w0", "w1"], ["w2"]],
                    "bob": [["w0"], ["w1", "w2"]],
                },
            },
            "inner": {
                "worlds": ["u0", "u1"],
                "atoms": {"q": ["u0"]},
                "indist": {
                    "ann": [["u0"], ["u1"]],
                    "bob": [["u0", "u1"]],
                },
            },
        },
        "levels": ["outer", "inner"],
        "actual": ["w0", "u0"],
        "query": "q",
        "bundle": None,
        "nested_bundle": None,
    }


def flip_neg_recursive(model: Mapping[str, Any]) -> dict[str, Any]:
    """Minimal task-changing twin: make the inner reports share a world."""
    foil = copy.deepcopy(model)
    nested = dict(foil.get("nested_bundle") or {})
    if not nested or len(foil["levels"]) < 2:
        raise ValueError("not a nested-bundle instance")
    inner = foil["frames"][foil["levels"][1]]
    # Pick a world that sits in the first agent's inner cell, assign it to all.
    first_agent = next(iter(nested))
    cell = cell_of(inner, first_agent, nested[first_agent])
    if not cell:
        raise ValueError("empty local inner cell")
    shared = sorted(cell)[0]
    foil["nested_bundle"] = {agent: shared for agent in nested}
    meta = dict(foil.get("meta") or {})
    meta["flipped_from"] = NEG_RECURSIVE
    foil["meta"] = meta
    return foil


def generate_class(cls: str, seed: int, opacity: str = TRANSPARENT) -> dict[str, Any]:
    """Seeded instance of a named class. Membership is checked separately."""
    if cls == POS_PLAIN:
        if seed % 2 == 0:
            model = generate_model(
                depth=1, regime=TREE, opacity=opacity, order=0, seed=seed
            )
        else:
            model = _four_world_cover(common=True, seed=seed, opacity=opacity)
        model.setdefault("meta", {})["class"] = POS_PLAIN
        return model
    if cls == POS_RECURSIVE:
        model = generate_model(
            depth=2 + (seed % 2), regime=TREE, opacity=opacity, order=0, seed=seed
        )
        model["query"] = "q"
        model["bundle"] = None
        model["nested_bundle"] = None
        model.setdefault("meta", {})["class"] = POS_RECURSIVE
        return model
    if cls == NEG_LOCAL:
        model = generate_model(
            depth=1, regime=CYCLIC_SAT, opacity=TRANSPARENT, order=0, seed=seed
        )
        bundle = dict(model["bundle"])
        first = model["agents"][0]
        bundle[first] = "missing_world"
        model["bundle"] = bundle
        if opacity == OPAQUE:
            model = relabel_model(model, seed + 3)
            # restore a missing-world report after relabel (unmapped token)
            bundle = dict(model["bundle"])
            bundle[model["agents"][0]] = "missing_world"
            model["bundle"] = bundle
        model.setdefault("meta", {})["class"] = NEG_LOCAL
        return model
    if cls == NEG_PAIRWISE:
        model = generate_model(
            depth=1, regime=CYCLIC_UNSAT, opacity=opacity, order=0, seed=seed
        )
        model.setdefault("meta", {})["class"] = NEG_PAIRWISE
        return model
    if cls == NEG_DEEP:
        model = _four_world_cover(common=False, seed=seed, opacity=opacity)
        model.setdefault("meta", {})["class"] = NEG_DEEP
        return model
    if cls == NEG_RECURSIVE:
        base = handwritten_neg_recursive()
        # Vary inner world names / actual via seed while keeping the obstruction.
        rng = random.Random(seed)
        model = copy.deepcopy(base)
        if seed % 3 == 1:
            model["actual"] = [model["frames"]["outer"]["worlds"][0], "u0"]
            model["query"] = "p"
        elif seed % 3 == 2:
            model["query"] = ["and", "p", ["not", ["K", "ann", "p"]]]
        if opacity == OPAQUE:
            model = relabel_model(model, seed + 11)
        model.setdefault("meta", {})["class"] = NEG_RECURSIVE
        model["meta"]["seed"] = seed
        _ = rng
        return model
    raise ValueError(f"unknown class {cls}")


def classify(model: Mapping[str, Any]) -> Optional[str]:
    """Membership from structure. Ignores meta['class']."""
    sat = task_sat(model)
    flat = task_sat(flatten_task_model(model))
    loc = local_ok(model)
    pair = pairwise_ok(model)
    trip = triple_ok(model)
    glob = bundle_possible(model)
    n_agents = len(model["agents"])
    has_nested = model.get("nested_bundle") is not None
    if not loc:
        return NEG_LOCAL
    if not pair:
        return NEG_PAIRWISE
    if loc and pair and trip and glob is False and not has_nested and n_agents >= 4:
        return NEG_DEEP
    if loc and pair and (not sat) and flat and has_nested:
        return NEG_RECURSIVE
    if sat and (not flat):
        return POS_RECURSIVE
    if sat and flat and not has_nested:
        return POS_PLAIN
    return None


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
                depth=max(depth, 2),
                regime=CYCLIC_SAT,
                opacity=opacity,
                order=max(order, 3),
                seed=2 * (seed + 11) + 1,
            ),
        ),
        (
            "assembled_unsat",
            generate_model(
                depth=max(depth, 2),
                regime=CYCLIC_UNSAT,
                opacity=opacity,
                order=max(order, 3),
                seed=2 * (seed + 11) + 1,
            ),
        ),
        ("opaque_twin", relabel_model(configured, seed + 99)),
        (
            "order_heldout",
            generate_model(
                depth=max(depth, 2),
                regime=regime if regime != TREE else CYCLIC_SAT,
                opacity=opacity,
                order=max(3, order + 1),
                seed=seed + 17,
            ),
        ),
        ("neg_deep", handwritten_neg_deep()),
        ("neg_recursive", handwritten_neg_recursive()),
        ("modal_positive", KnowledgeProbe().generate(1, max(3, order + 1), TREE, OPAQUE, 2 * seed + 1)),
        ("modal_counterfactual", KnowledgeProbe().counterfactual(
            KnowledgeProbe().generate(1, max(3, order + 1), TREE, OPAQUE, 2 * seed + 1))),
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



class KnowledgeProbe:
    """Alternating-agent reachability with a boundary reached at exact modal depth."""

    def sequence(self, count, index=0):
        if count == 0:
            return ()
        return (("ann", "bob", "cara", "dan")[index % 4],) + self.sequence(count - 1, index + 1)

    def partition(self, worlds, agent, index=0):
        if not worlds:
            return ()
        if index % 4 == agent and worlds[1:]:
            return (tuple(worlds[:2]),) + self.partition(worlds[2:], agent, index + 2)
        return ((worlds[0],),) + self.partition(worlds[1:], agent, index + 1)

    def formula(self, agents, atom):
        if not agents:
            return atom
        return "K", agents[0], self.formula(agents[1:], atom)

    def generate(self, depth, order, regime, opacity, seed):
        model = handwritten_neg_deep()
        frame = model["frames"]["outer"]
        count = max(3, order)
        worlds = tuple(map(str, range(count + 1)))
        frame["worlds"] = worlds
        frame["atoms"]["p"] = worlds if seed % 2 else worlds[:-1]
        frame["indist"]["ann"] = self.partition(worlds, 0)
        frame["indist"]["bob"] = self.partition(worlds, 1)
        frame["indist"]["cara"] = self.partition(worlds, 2)
        frame["indist"]["dan"] = self.partition(worlds, 3)
        agents = self.sequence(count)
        model["query"] = self.formula(agents, "p")
        model["knowledge_probe"] = agents, "p"
        model["actual"] = (worlds[0],)
        model["bundle"]["ann"] = worlds[0]
        model["bundle"]["bob"] = worlds[0]
        model["bundle"]["cara"] = worlds[0]
        model["bundle"]["dan"] = worlds[0]
        if depth == 1 and regime == CYCLIC_UNSAT:
            model["bundle"]["dan"] = worlds[-1]
        if depth > 1:
            nested = handwritten_neg_deep()
            inner = nested["frames"]["outer"]
            inner["atoms"]["p"] = ()
            inner["atoms"]["q"] = ("w0",)
            model["frames"]["inner"] = inner
            model["levels"] = ("outer",) + ("inner",) * (depth - 1)
            model["actual"] += ("w0",) * (depth - 1)
            model["nested_bundle"] = nested["bundle"]
            if regime != CYCLIC_UNSAT:
                model["nested_bundle"]["dan"] = "w3"
        if regime == TREE:
            model["bundle"] = None
            model["nested_bundle"] = None
        return relabel_model(model, seed) if opacity == OPAQUE else model

    def successors(self, frame, agent, states):
        if not states:
            return set()
        return cell_of(frame, agent, states[0]) | self.successors(frame, agent, states[1:])

    def layers(self, frame, agents, states):
        if not agents:
            return (tuple(sorted(states)),)
        next_states = tuple(self.successors(frame, agents[0], tuple(states)))
        return (tuple(sorted(states)),) + self.layers(frame, agents[1:], next_states)

    def certificate(self, model):
        agents, atom = model["knowledge_probe"]
        return self.layers(model["frames"][model["levels"][0]], agents, (model["actual"][0],))

    def verify(self, model, raw):
        try:
            return self.same_layers(tuple(raw), self.certificate(model))
        except TypeError:
            return 0

    def same_layers(self, submitted, expected):
        if not expected:
            return int(not submitted)
        if not submitted or tuple(sorted(submitted[0])) != tuple(sorted(expected[0])):
            return 0
        return self.same_layers(submitted[1:], expected[1:])

    def counterfactual(self, model):
        foil = copy.deepcopy(model)
        frame = foil["frames"][foil["levels"][0]]
        terminal = frame["worlds"][-1]
        values = set(frame["atoms"]["p"])
        values.symmetric_difference_update((terminal,))
        frame["atoms"]["p"] = tuple(sorted(values))
        return foil
