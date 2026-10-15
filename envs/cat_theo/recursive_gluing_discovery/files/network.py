"""Discovery sibling of recursive_gluing (v0).

v0 is the control: the agent receives complete bijective overlap tables and
can solve them as an ordinary finite CSP. Recursion lives in the generator,
not in the solving semantics.

This module withholds those tables. The public instance shows:

* each region's local cycle (a rotation of its states);
* a fully observed root gadget;
* a few observed compatible pairs on other overlaps;
* some assembly overlaps with no listed pairs;
* the copy index of the recursively substituted branch template.

The judge scores against the hidden complete relations. A generic CSP on the
listed pairs therefore fails: it either treats missing pairs as "no constraint"
or treats the sparse probes as the whole relation. Completing the tables is
cheap if the solver discovers that overlap maps intertwine the local cycles
(an affine transport on the cycle indices) and that unprobed assembly edges
are the composition of those transports. That is the structural advantage.

Offline arms (tests only; not shipped to the agent):

* ``arm_generic_sparse`` — CSP on listed pairs; missing edges unconstrained.
* ``arm_given_latent`` — solves the hidden complete instance.
* ``arm_discover`` — fit cycle-intertwining maps, compose unprobed edges, solve.
"""
from __future__ import annotations

import random
from collections import defaultdict, deque
from typing import Any, Callable, Mapping, Optional


TREE = "tree"
CYCLIC_SAT = "cyclic_sat"
CYCLIC_UNSAT = "cyclic_unsat"
TRANSLATION = "translation"
AFFINE = "affine"
VALID_REGIMES = (TREE, CYCLIC_SAT, CYCLIC_UNSAT)
VALID_FAMILIES = (TRANSLATION, AFFINE)
PRIMES = (5, 7, 13)

CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "unprobed_reuse",
    "heldout_affine",
    "relabel_twin",
    "deterministic",
)

ARM_GENERIC = "generic_sparse"
ARM_GIVEN_LATENT = "given_latent"
ARM_DISCOVER = "discover"


class OracleBudgetExceeded(RuntimeError):
    """Search exceeded its node budget. This is not evidence of unsatisfiability."""


# ---------------------------------------------------------------------------
# Complete-instance helpers (hidden from the agent)
# ---------------------------------------------------------------------------

def overlap_pairs(overlap: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [(str(a), str(b)) for a, b in overlap.get("pairs") or []]


def region_count(instance: Mapping[str, Any]) -> int:
    return len(instance["regions"])


def cartesian_size(instance: Mapping[str, Any]) -> int:
    size = 1
    for spec in instance["regions"].values():
        size *= max(len(spec["domain"]), 1)
    return size


def max_name_depth(instance: Mapping[str, Any]) -> int:
    if not instance["regions"]:
        return 0
    return max(rid.count("/") for rid in instance["regions"])


def has_unprobed_overlap(public: Mapping[str, Any]) -> bool:
    return any(len(overlap.get("pairs") or []) == 0 for overlap in public["overlaps"])


def listed_pair_count(public: Mapping[str, Any]) -> int:
    return sum(len(overlap.get("pairs") or []) for overlap in public["overlaps"])


def complete_pair_count(complete: Mapping[str, Any]) -> int:
    return sum(len(overlap.get("pairs") or []) for overlap in complete["overlaps"])


def validate_assignment(
    instance: Mapping[str, Any], assignment: Mapping[str, Any]
) -> tuple[bool, str]:
    regions = instance["regions"]
    if set(assignment) != set(regions):
        return False, "assignment region set does not match the instance"
    for rid, value in assignment.items():
        if value not in regions[rid]["domain"]:
            return False, f"value {value!r} is not in the domain of {rid!r}"
    for overlap in instance["overlaps"]:
        pairs = set(overlap_pairs(overlap))
        if not pairs:
            continue
        left, right = overlap["left"], overlap["right"]
        if (assignment[left], assignment[right]) not in pairs:
            return False, f"overlap {left}--{right} is violated"
    return True, "ok"


def _relation_index(
    instance: Mapping[str, Any],
) -> tuple[dict[tuple[str, str], dict[str, set[str]]], dict[str, set[str]]]:
    allowed: dict[tuple[str, str], dict[str, set[str]]] = {}
    neighbors: dict[str, set[str]] = {rid: set() for rid in instance["regions"]}
    for overlap in instance["overlaps"]:
        u, v = str(overlap["left"]), str(overlap["right"])
        pairs = overlap_pairs(overlap)
        if not pairs:
            continue
        fwd: dict[str, set[str]] = defaultdict(set)
        rev: dict[str, set[str]] = defaultdict(set)
        for a, b in pairs:
            fwd[a].add(b)
            rev[b].add(a)
        neighbors[u].add(v)
        neighbors[v].add(u)
        allowed[(u, v)] = {key: set(val) for key, val in fwd.items()}
        allowed[(v, u)] = {key: set(val) for key, val in rev.items()}
    return allowed, neighbors


def oracle_solution(
    instance: Mapping[str, Any], max_nodes: int = 200_000
) -> Optional[dict[str, str]]:
    """Complete finite-CSP solver on whatever pair tables ``instance`` carries."""
    rids = sorted(instance["regions"])
    domains = {rid: set(instance["regions"][rid]["domain"]) for rid in rids}
    if any(len(dom) == 0 for dom in domains.values()):
        return None
    allowed, neighbors = _relation_index(instance)
    nodes = [0]

    def revise(dom: dict[str, set[str]], u: str, v: str) -> bool:
        rel = allowed.get((u, v), {})
        keep = set()
        vs = dom[v]
        dropped = False
        for a in dom[u]:
            if rel.get(a, set()) & vs:
                keep.add(a)
            else:
                dropped = True
        if dropped:
            dom[u] = keep
        return dropped

    def ac3(dom: dict[str, set[str]]) -> bool:
        queue = deque(allowed)
        while queue:
            u, v = queue.popleft()
            if revise(dom, u, v):
                if not dom[u]:
                    return False
                for w in neighbors[u]:
                    if w != v:
                        queue.append((w, u))
        return True

    def search(dom: dict[str, set[str]]) -> Optional[dict[str, str]]:
        nodes[0] += 1
        if nodes[0] > max_nodes:
            raise OracleBudgetExceeded(
                f"oracle exceeded {max_nodes} nodes; refusing to call this unsat"
            )
        if not ac3(dom):
            return None
        unassigned = [rid for rid in rids if len(dom[rid]) > 1]
        if not unassigned:
            assignment = {rid: next(iter(sorted(dom[rid]))) for rid in rids}
            ok, _ = validate_assignment(instance, assignment)
            return assignment if ok else None
        unassigned.sort(key=lambda rid: (len(dom[rid]), rid))
        rid = unassigned[0]
        for value in sorted(dom[rid]):
            child = {key: set(val) for key, val in dom.items()}
            child[rid] = {value}
            found = search(child)
            if found is not None:
                return found
        return None

    return search({rid: set(dom) for rid, dom in domains.items()})


def oracle_satisfiable(instance: Mapping[str, Any], max_nodes: int = 200_000) -> bool:
    return oracle_solution(instance, max_nodes=max_nodes) is not None


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def _opaque_label(rng: random.Random, used: set[str]) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while True:
        token = "".join(rng.choice(alphabet) for _ in range(5))
        if token not in used:
            used.add(token)
            return token


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    return all(n % d != 0 for d in range(2, int(n**0.5) + 1))


def generate_bundle(
    *,
    depth: int,
    domain_size: int,
    regime: str,
    family: str,
    seed: int,
) -> dict[str, Any]:
    """Return ``{"public": ..., "complete": ...}`` for one recursive instance."""
    if depth < 1:
        raise ValueError("depth must be >= 1")
    if domain_size not in PRIMES and not _is_prime(domain_size):
        raise ValueError("domain_size must be prime so cycle-intertwiners are unique")
    if regime not in VALID_REGIMES:
        raise ValueError(f"unknown regime {regime!r}")
    if family not in VALID_FAMILIES:
        raise ValueError(f"unknown family {family!r}")

    struct_rng = random.Random(seed)
    label_rng = random.Random((int(seed) + 1) * 10007)
    n = int(domain_size)
    hidden: dict[str, int] = {}

    def rec(prefix: str, remaining: int) -> None:
        hidden[prefix] = struct_rng.randrange(n)
        if remaining > 0:
            rec(prefix + "/L", remaining - 1)
            rec(prefix + "/R", remaining - 1)

    rec("root", depth)

    frames: dict[str, list[str]] = {}
    regions: dict[str, dict[str, Any]] = {}
    rotations: dict[str, int] = {}
    for rid in sorted(hidden):
        used: set[str] = set()
        labels_by_hidden = [_opaque_label(label_rng, used) for _ in range(n)]
        frames[rid] = labels_by_hidden
        domain = list(labels_by_hidden)
        label_rng.shuffle(domain)
        rot = label_rng.randrange(n)
        rotations[rid] = rot
        cycle = [labels_by_hidden[(rot + t) % n] for t in range(n)]
        regions[rid] = {"domain": domain, "cycle": cycle}

    def slope(u: str, v: str) -> int:
        if family == TRANSLATION:
            return 1
        return 2 + (abs(hash((u, v, seed))) % (n - 2))

    def intercept(u: str, v: str, a: int) -> int:
        return (hidden[v] - a * hidden[u]) % n

    def inv_slope(a: int) -> int:
        return pow(int(a), -1, n)

    def affine_pairs(u: str, v: str, a: int, b: int) -> list[list[str]]:
        return [[frames[u][i], frames[v][(a * i + b) % n]] for i in range(n)]

    def add_complete(u: str, v: str, a: int, b: int) -> dict[str, Any]:
        return {"left": u, "right": v, "pairs": affine_pairs(u, v, a, b), "a": a, "b": b}

    complete_overlaps: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    tree_ab: dict[tuple[str, str], tuple[int, int]] = {}

    def register(u: str, v: str, a: int, b: int, kind: str) -> None:
        complete_overlaps.append(add_complete(u, v, a, b))
        meta.append({"left": u, "right": v, "a": a, "b": b, "kind": kind})

    def compose_ab(a1: int, b1: int, a2: int, b2: int) -> tuple[int, int]:
        # x |-> a1 x + b1 |-> a2 (a1 x + b1) + b2
        return (a2 * a1) % n, (a2 * b1 + b2) % n

    def tree_path_ab(src: str, dst: str) -> tuple[int, int]:
        parent: dict[str, Optional[str]] = {src: None}
        queue: deque[str] = deque([src])
        while queue:
            node = queue.popleft()
            if node == dst:
                break
            for suffix in ("/L", "/R"):
                child = node + suffix
                if child in hidden and child not in parent:
                    parent[child] = node
                    queue.append(child)
            if "/" in node:
                up = node.rsplit("/", 1)[0]
                if up in hidden and up not in parent:
                    parent[up] = node
                    queue.append(up)
        if dst not in parent:
            raise RuntimeError(f"no tree path {src} -> {dst}")
        chain = []
        cur: Optional[str] = dst
        while cur is not None and cur != src:
            prev = parent[cur]
            chain.append((prev, cur))
            cur = prev
        chain.reverse()
        a_tot, b_tot = 1, 0
        for u, v in chain:
            if (u, v) in tree_ab:
                a, b = tree_ab[(u, v)]
            else:
                a_uv, b_uv = tree_ab[(v, u)]
                a = inv_slope(a_uv)
                b = (-a * b_uv) % n
            a_tot, b_tot = compose_ab(a_tot, b_tot, a, b)
        return a_tot, b_tot

    for rid in hidden:
        for suffix in ("/L", "/R"):
            child = rid + suffix
            if child not in hidden:
                continue
            a = slope(rid, child)
            b = intercept(rid, child, a)
            tree_ab[(rid, child)] = (a, b)
            register(rid, child, a, b, "tree")

    if regime in (CYCLIC_SAT, CYCLIC_UNSAT):
        for rid in hidden:
            left, right = rid + "/L", rid + "/R"
            if left not in hidden or right not in hidden:
                continue
            a, b = tree_path_ab(left, right)
            if regime == CYCLIC_UNSAT and rid == "root":
                b = (b + 1) % n
            register(left, right, a, b, "cycle")
        deep = "root" + "/L" * depth
        if depth >= 2 and deep in hidden:
            a, b = tree_path_ab("root", deep)
            register("root", deep, a, b, "skip")

    copies = []
    for rid in sorted(hidden):
        left, right = rid + "/L", rid + "/R"
        if left in hidden and right in hidden:
            copies.append({"I": rid, "L": left, "R": right})

    # Public pair tables: full gadget at the root tree edges; 2 probes on other
    # tree/cycle edges; nothing on skip-level and on deeper sibling edges.
    public_overlaps = []
    for item, complete in zip(meta, complete_overlaps):
        kind = item["kind"]
        u, v = item["left"], item["right"]
        full = [[a, b] for a, b in complete["pairs"]]
        if kind == "tree" and u == "root":
            pairs = full
        elif kind == "skip" or (kind == "cycle" and u != "root/L"):
            pairs = []
        else:
            ts = list(range(n))
            label_rng.shuffle(ts)
            chosen = ts[:2]
            a, b = item["a"], item["b"]
            pairs = [[frames[u][t], frames[v][(a * t + b) % n]] for t in chosen]
        public_overlaps.append({"left": u, "right": v, "pairs": pairs})

    public_regions = {
        rid: {"domain": list(spec["domain"]), "cycle": list(spec["cycle"])}
        for rid, spec in regions.items()
    }
    complete_regions = {
        rid: {"domain": list(spec["domain"])} for rid, spec in regions.items()
    }
    complete = {
        "regions": complete_regions,
        "overlaps": [
            {"left": ov["left"], "right": ov["right"], "pairs": [list(p) for p in ov["pairs"]]}
            for ov in complete_overlaps
        ],
    }
    public = {
        "regions": public_regions,
        "overlaps": public_overlaps,
        "copies": copies,
        "gadget": "root",
    }
    return {
        "public": public,
        "complete": complete,
        "family": family,
        "regime": regime,
        "depth": depth,
        "domain_size": n,
        "seed": seed,
    }


def relabel_bundle(bundle: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    public = bundle["public"]
    mapping: dict[str, dict[str, str]] = {}
    new_pub_regions: dict[str, dict[str, Any]] = {}
    for rid, spec in public["regions"].items():
        used: set[str] = set()
        local = {old: _opaque_label(rng, used) for old in spec["domain"]}
        mapping[rid] = local
        new_pub_regions[rid] = {
            "domain": [local[old] for old in spec["domain"]],
            "cycle": [local[old] for old in spec["cycle"]],
        }

    def remap_overlaps(overlaps: list[dict[str, Any]], include_empty: bool) -> list[dict[str, Any]]:
        out = []
        for overlap in overlaps:
            left, right = overlap["left"], overlap["right"]
            lm, rm = mapping[left], mapping[right]
            pairs = [[lm[a], rm[b]] for a, b in overlap_pairs(overlap)]
            if pairs or include_empty:
                out.append({"left": left, "right": right, "pairs": pairs})
        return out

    new_public = {
        "regions": new_pub_regions,
        "overlaps": remap_overlaps(public["overlaps"], include_empty=True),
        "copies": list(public["copies"]),
        "gadget": public["gadget"],
    }
    complete = bundle["complete"]
    new_complete = {
        "regions": {rid: {"domain": list(new_pub_regions[rid]["domain"])} for rid in complete["regions"]},
        "overlaps": remap_overlaps(complete["overlaps"], include_empty=False),
    }
    return {
        "public": new_public,
        "complete": new_complete,
        "family": bundle["family"],
        "regime": bundle["regime"],
        "depth": bundle["depth"],
        "domain_size": bundle["domain_size"],
        "seed": bundle["seed"],
    }


def example_visible_sat() -> dict[str, Any]:
    """Tiny fully-listed two-region instance. Baseline first-value greedy succeeds."""
    return {
        "regions": {
            "cell_a": {"domain": ["p", "q"], "cycle": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"], "cycle": ["r", "s"]},
        },
        "overlaps": [{"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]}],
        "copies": [],
        "gadget": "cell_a",
    }


def example_visible_complete() -> dict[str, Any]:
    return {
        "regions": {
            "cell_a": {"domain": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"]},
        },
        "overlaps": [{"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]}],
    }


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------

def _cycle_index(cycle: list[str], label: str) -> int:
    return cycle.index(label)


def _step(cycle: list[str], label: str, steps: int) -> str:
    n = len(cycle)
    return cycle[(_cycle_index(cycle, label) + steps) % n]


def fit_cycle_intertwiner(
    left_cycle: list[str], right_cycle: list[str], probes: list[tuple[str, str]]
) -> Optional[list[list[str]]]:
    """Complete a bijection that intertwines two cycles, or None if probes conflict."""
    if not probes:
        return None
    n = len(left_cycle)
    if n != len(right_cycle) or n < 2:
        return None
    x1, y1 = probes[0]
    if x1 not in left_cycle or y1 not in right_cycle:
        return None
    matches: list[int] = []
    for a in range(1, n):
        ok = True
        for x, y in probes:
            if x not in left_cycle or y not in right_cycle:
                ok = False
                break
            k = (_cycle_index(left_cycle, x) - _cycle_index(left_cycle, x1)) % n
            if _step(right_cycle, y1, a * k) != y:
                ok = False
                break
        if ok:
            matches.append(a)
    if not matches:
        return None
    a = matches[0]
    if len(probes) >= 2 and matches != [a]:
        # Two independent probes should pin a unique slope on a prime cycle.
        x2, y2 = probes[1]
        k = (_cycle_index(left_cycle, x2) - _cycle_index(left_cycle, x1)) % n
        if k % n == 0:
            a = matches[0]
        else:
            a = matches[0]
    pairs = [[_step(left_cycle, x1, t), _step(right_cycle, y1, a * t)] for t in range(n)]
    return pairs


def compose_bijections(
    left_right: list[list[str]], right_end: list[list[str]]
) -> list[list[str]]:
    mid = {a: b for a, b in left_right}
    nxt = {a: b for a, b in right_end}
    return [[src, nxt[mid[src]]] for src in mid if mid[src] in nxt]


def invert_pairs(pairs: list[list[str]]) -> list[list[str]]:
    return [[b, a] for a, b in pairs]


def arm_discover(public: Mapping[str, Any]) -> dict[str, Any]:
    """Intended structural solver: complete tables from cycles, then CSP."""
    regions = public["regions"]
    completed: dict[tuple[str, str], list[list[str]]] = {}
    pending_empty: list[tuple[str, str]] = []
    for overlap in public["overlaps"]:
        u, v = overlap["left"], overlap["right"]
        probes = overlap_pairs(overlap)
        if not probes:
            pending_empty.append((u, v))
            continue
        filled = fit_cycle_intertwiner(regions[u]["cycle"], regions[v]["cycle"], probes)
        if filled is None:
            return {"status": "unsat"}
        completed[(u, v)] = filled

    # Fill unprobed edges by composing completed bijections along a path.
    def neighbours(node: str) -> list[tuple[str, list[list[str]]]]:
        out = []
        for (u, v), pairs in completed.items():
            if u == node:
                out.append((v, pairs))
            elif v == node:
                out.append((u, invert_pairs(pairs)))
        return out

    def transport(src: str, dst: str) -> Optional[list[list[str]]]:
        if src == dst:
            cycle = regions[src]["cycle"]
            return [[lab, lab] for lab in cycle]
        seen = {src}
        queue: deque[tuple[str, list[list[str]]]] = deque(
            [(nbr, pairs) for nbr, pairs in neighbours(src)]
        )
        for nbr, _pairs in list(queue):
            seen.add(nbr)
        while queue:
            node, mapping = queue.popleft()
            if node == dst:
                return mapping
            for nbr, step in neighbours(node):
                if nbr in seen:
                    continue
                seen.add(nbr)
                queue.append((nbr, compose_bijections(mapping, step)))
        return None

    for u, v in pending_empty:
        filled = transport(u, v)
        if filled is None:
            # An adjacency we cannot complete is not evidence of unsat.
            continue
        completed[(u, v)] = filled

    instance = {
        "regions": {rid: {"domain": spec["domain"]} for rid, spec in regions.items()},
        "overlaps": [
            {"left": u, "right": v, "pairs": pairs} for (u, v), pairs in completed.items()
        ],
    }
    assignment = oracle_solution(instance)
    if assignment is None:
        return {"status": "unsat"}
    return {"status": "sat", "assignment": assignment}


def arm_given_latent(complete: Mapping[str, Any]) -> dict[str, Any]:
    """Cheating arm: the hidden complete tables are given."""
    assignment = oracle_solution(complete)
    if assignment is None:
        return {"status": "unsat"}
    return {"status": "sat", "assignment": assignment}


def arm_generic_sparse(public: Mapping[str, Any]) -> dict[str, Any]:
    """Control arm: listed pairs are the whole relation; empty edges unconstrained."""
    instance = {
        "regions": {rid: {"domain": spec["domain"]} for rid, spec in public["regions"].items()},
        "overlaps": [
            {"left": ov["left"], "right": ov["right"], "pairs": [list(p) for p in ov["pairs"]]}
            for ov in public["overlaps"]
            if ov.get("pairs")
        ],
    }
    assignment = oracle_solution(instance)
    if assignment is None:
        return {"status": "unsat"}
    return {"status": "sat", "assignment": assignment}


def translation_only_discover(public: Mapping[str, Any]) -> dict[str, Any]:
    """Foil: force slope a=1. Fails held-out affine instances."""
    forced = {
        "regions": public["regions"],
        "overlaps": [],
        "copies": public.get("copies", []),
        "gadget": public.get("gadget"),
    }
    for overlap in public["overlaps"]:
        probes = overlap_pairs(overlap)
        if len(probes) >= 2:
            # Keep probes; arm_discover will still try all a. Simulate a=1 by
            # expanding only the translation orbit and replacing probes with it.
            u, v = overlap["left"], overlap["right"]
            left_c = public["regions"][u]["cycle"]
            right_c = public["regions"][v]["cycle"]
            x1, y1 = probes[0]
            pairs = [[_step(left_c, x1, t), _step(right_c, y1, t)] for t in range(len(left_c))]
            forced["overlaps"].append({"left": u, "right": v, "pairs": pairs})
        else:
            forced["overlaps"].append(
                {"left": overlap["left"], "right": overlap["right"], "pairs": [list(p) for p in probes]}
            )
    assignment = oracle_solution(
        {
            "regions": {rid: {"domain": spec["domain"]} for rid, spec in public["regions"].items()},
            "overlaps": forced["overlaps"],
        }
    )
    if assignment is None:
        return {"status": "unsat"}
    return {"status": "sat", "assignment": assignment}


# ---------------------------------------------------------------------------
# Output contract and grading
# ---------------------------------------------------------------------------

def parse_solve_output(
    complete: Mapping[str, Any], raw: Any
) -> tuple[Optional[dict[str, Any]], str]:
    if not isinstance(raw, dict):
        return None, "output is not a dict"
    status = raw.get("status")
    if status == "unsat":
        return {"status": "unsat"}, ""
    if status != "sat":
        return None, "status must be 'sat' or 'unsat'"
    assignment = raw.get("assignment")
    if not isinstance(assignment, dict):
        return None, "sat output is missing an assignment mapping"
    coerced = {str(key): value for key, value in assignment.items()}
    ok, reason = validate_assignment(complete, coerced)
    if not ok:
        return None, reason
    return {"status": "sat", "assignment": coerced}, ""


def evaluate_against_complete(
    solve_fn: Callable[[dict[str, Any]], Any],
    public: dict[str, Any],
    complete: dict[str, Any],
) -> bool:
    import copy

    sat = oracle_satisfiable(complete)
    try:
        raw = solve_fn(copy.deepcopy(public))
    except Exception:
        return False
    parsed, err = parse_solve_output(complete, raw)
    if err or parsed is None:
        return False
    if sat:
        return parsed["status"] == "sat"
    return parsed["status"] == "unsat"


def build_grade_bundles(*, depth: int, domain_size: int, regime: str, family: str, seed: int):
    configured = generate_bundle(
        depth=depth, domain_size=domain_size, regime=regime, family=family, seed=seed
    )
    items = [
        (
            "local_visible",
            {"public": example_visible_sat(), "complete": example_visible_complete()},
        ),
        ("configured", configured),
        (
            "assembled_sat",
            generate_bundle(
                depth=max(depth, 2),
                domain_size=domain_size,
                regime=CYCLIC_SAT,
                family=family,
                seed=seed + 11,
            ),
        ),
        (
            "assembled_unsat",
            generate_bundle(
                depth=max(depth, 1),
                domain_size=domain_size,
                regime=CYCLIC_UNSAT,
                family=family,
                seed=seed + 13,
            ),
        ),
        (
            "unprobed_reuse",
            generate_bundle(
                depth=max(depth, 2),
                domain_size=domain_size,
                regime=CYCLIC_SAT,
                family=family,
                seed=seed + 17,
            ),
        ),
        (
            "heldout_affine",
            generate_bundle(
                depth=max(depth, 2),
                domain_size=max(domain_size, 7),
                regime=CYCLIC_SAT,
                family=AFFINE,
                seed=seed + 19,
            ),
        ),
        ("relabel_twin", relabel_bundle(configured, seed + 99)),
    ]
    return items


def grade_solver(
    solve_fn: Callable[[dict[str, Any]], Any],
    *,
    depth: int,
    domain_size: int,
    regime: str,
    family: str,
    seed: int,
) -> dict[str, bool]:
    import copy

    items = build_grade_bundles(
        depth=depth, domain_size=domain_size, regime=regime, family=family, seed=seed
    )
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, bundle in items:
        checks[name] = evaluate_against_complete(solve_fn, bundle["public"], bundle["complete"])
    configured = named["configured"]
    try:
        first = solve_fn(copy.deepcopy(configured["public"]))
        second = solve_fn(copy.deepcopy(configured["public"]))
        parsed, err = parse_solve_output(configured["complete"], first)
        checks["deterministic"] = first == second and parsed is not None and not err
    except Exception:
        checks["deterministic"] = False
    return checks
