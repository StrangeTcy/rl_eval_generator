"""Compact recursive constraint grammar for recursive_gluing_discovery.

v0 (`recursive_gluing`) is the expanded-CSP control. This module never builds
that graph for the agent. The instance is a grammar: leaf pair tables, per-depth
transport tables, a depth, and an optional root closing relation. Unfolding is a
complete binary tree of 2**(depth+1)-1 occurrences; the compact oracle summarises
each module type at each remaining depth by its realisable (enter, leave) pairs.

Supported class: serial composition of binary transducers whose leaf relation
is a translation on Z/qZ (q odd prime) presented only as pair tables.
"""
from __future__ import annotations

import json
import random
import time
from collections import defaultdict, deque
from typing import Any, Callable, Mapping, Optional


TREE = "tree"
CYCLIC_SAT = "cyclic_sat"
CYCLIC_UNSAT = "cyclic_unsat"
TRANSPARENT = "transparent"
OPAQUE = "opaque"
CLEAN = "clean"
DECOY = "decoy"
VALID_REGIMES = (TREE, CYCLIC_SAT, CYCLIC_UNSAT)
VALID_OPACITY = (TRANSPARENT, OPAQUE)
VALID_AMBIGUITY = (CLEAN, DECOY)
PRIMES = (3, 5, 7)

CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "decoy_heldout",
    "heldout_twist",
    "deterministic",
)
PUBLIC_KEYS = ("root", "depth", "modules", "productions", "closing")
MAX_EXPAND_DEPTH = 4


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. This is not evidence of unsatisfiability."""


def unfolded_occurrences(depth: int) -> int:
    """Complete binary tree of stem/leaf copies: 2**(depth+1) - 1."""
    return (1 << (depth + 1)) - 1


def unfolded_leaves(depth: int) -> int:
    return 1 << depth


def unfolded_internal(depth: int) -> int:
    """Stem occurrences: 2**depth - 1."""
    return (1 << depth) - 1


def expanded_port_variables(depth: int) -> int:
    """One enter and one leave variable per occurrence."""
    return 2 * unfolded_occurrences(depth)


def expanded_overlap_count(depth: int, *, closing: bool) -> int:
    """Leaf pair-tables + three wirings per internal + optional root closing.

    leaves + 3 * internals + closing = 2**d + 3*(2**d - 1) + [0|1]
    = 2**(d+2) - 3 + [0|1].
    """
    return (1 << (depth + 2)) - 3 + (1 if closing else 0)


def grammar_has_closing(grammar: Mapping[str, Any]) -> bool:
    closing = grammar.get("closing")
    return bool(closing and closing.get("pairs"))


def expanded_occurrence_count(instance: Mapping[str, Any]) -> int:
    names = {rid.rsplit("/", 1)[0] for rid in instance["regions"]}
    return len(names)


def certificate_bytes(cert: Mapping[str, Any]) -> int:
    return len(json.dumps(cert, sort_keys=True, separators=(",", ":")))


def summary_depth_keys(realizable: Mapping[str, Mapping[str, list]]) -> int:
    return sum(len(depths) for depths in realizable.values())


def public_grammar(grammar: Mapping[str, Any]) -> dict[str, Any]:
    """Agent-facing instance: no generator metadata."""
    return {key: grammar[key] for key in PUBLIC_KEYS}


def compact_input_bytes(grammar: Mapping[str, Any]) -> int:
    return len(json.dumps(public_grammar(grammar), sort_keys=True, separators=(",", ":")))


def summary_cells(realizable: Mapping[str, Mapping[str, list]]) -> int:
    return sum(len(pairs) for depths in realizable.values() for pairs in depths.values())


def _pair_set(pairs: list) -> set[tuple[str, str]]:
    return {(str(a), str(b)) for a, b in pairs}


def _as_map(pairs: list) -> dict[str, str]:
    return {str(a): str(b) for a, b in pairs}


def closing_pairs(grammar: Mapping[str, Any]) -> Optional[set[tuple[str, str]]]:
    closing = grammar.get("closing")
    if not closing:
        return None
    return _pair_set(closing["pairs"])


def child_types_at_depth(grammar: Mapping[str, Any], remaining: int) -> tuple[str, str]:
    rule = grammar["productions"]["stem"]
    if remaining <= 1:
        return rule["depth_1"]["left"], rule["depth_1"]["right"]
    return rule["deeper"]["left"], rule["deeper"]["right"]


def wiring_at_depth(grammar: Mapping[str, Any], remaining: int) -> dict[str, list]:
    rule = grammar["productions"]["stem"]
    if remaining <= 1:
        return rule["depth_1"]["wiring"]
    return rule["deeper"]["wiring"]


def compose_branch(
    left_pairs: set[tuple[str, str]],
    right_pairs: set[tuple[str, str]],
    wiring: Mapping[str, list],
) -> set[tuple[str, str]]:
    enter = _as_map(wiring["enter"])  # parent_enter -> left_enter
    mid = _as_map(wiring["mid"])  # left_leave -> right_enter
    leave = _as_map(wiring["leave"])  # right_leave -> parent_leave
    inv_enter = {v: k for k, v in enter.items()}
    right_by_enter: dict[str, list[str]] = defaultdict(list)
    for e_r, l_r in right_pairs:
        right_by_enter[e_r].append(l_r)
    out: set[tuple[str, str]] = set()
    for e_l, l_l in left_pairs:
        parent_enter = inv_enter.get(e_l)
        if parent_enter is None:
            continue
        right_enter = mid.get(l_l)
        if right_enter is None:
            continue
        for l_r in right_by_enter.get(right_enter, ()):
            parent_leave = leave.get(l_r)
            if parent_leave is not None:
                out.add((parent_enter, parent_leave))
    return out


def compact_summaries(
    grammar: Mapping[str, Any], max_nodes: int = 2_000_000
) -> dict[str, dict[str, list[list[str]]]]:
    """Bottom-up realisable (enter, leave) pairs per type and remaining depth.

    Completeness: S(leaf, 0) is the listed table; S(stem, k) is serial
    composition of the child summaries after that depth's transport tables.
    That is the inductive definition of the unfolded binary tree, so the
    summary is sound and complete for this grammar. The algorithm never
    allocates unfolded occurrences.
    """
    depth = int(grammar["depth"])
    modules = grammar["modules"]
    nodes = [0]
    realizable: dict[str, dict[int, set[tuple[str, str]]]] = {name: {} for name in modules}

    def charge(n: int = 1) -> None:
        nodes[0] += n
        if nodes[0] > max_nodes:
            raise OracleBudgetExceeded(
                f"oracle exceeded {max_nodes} steps; refusing to call this unsat"
            )

    for name, spec in modules.items():
        if spec["kind"] == "leaf":
            realizable[name][0] = _pair_set(spec["pairs"])
            charge(len(spec["pairs"]) + 1)

    for k in range(1, depth + 1):
        charge(1)
        left_t, right_t = child_types_at_depth(grammar, k)
        wiring = wiring_at_depth(grammar, k)
        left_d = k - 1 if modules[left_t]["kind"] == "branch" else 0
        right_d = k - 1 if modules[right_t]["kind"] == "branch" else 0
        left_set = realizable[left_t][left_d]
        right_set = realizable[right_t][right_d]
        charge(len(left_set) * max(len(right_set), 1))
        realizable["stem"][k] = compose_branch(left_set, right_set, wiring)

    out: dict[str, dict[str, list[list[str]]]] = {}
    for name, by_depth in realizable.items():
        out[name] = {
            str(k): sorted([list(p) for p in pairs])
            for k, pairs in sorted(by_depth.items())
        }
    return out


def root_accepted_pairs(
    grammar: Mapping[str, Any], summaries: Mapping[str, Mapping[str, list]]
) -> set[tuple[str, str]]:
    depth = str(int(grammar["depth"]))
    root = grammar["root"]
    pairs = _pair_set(summaries[root][depth])
    closing = closing_pairs(grammar)
    if closing is None:
        return pairs
    return pairs & closing


def grammar_satisfiable(grammar: Mapping[str, Any]) -> bool:
    return bool(root_accepted_pairs(grammar, compact_summaries(grammar)))


def reference_certificate(grammar: Mapping[str, Any]) -> dict[str, Any]:
    summaries = compact_summaries(grammar)
    accepted = root_accepted_pairs(grammar, summaries)
    status = "sat" if accepted else "unsat"
    cert = {"status": status, "realizable": summaries}
    if accepted:
        root_pair = sorted(accepted)[0]
        cert["root_enter"] = root_pair[0]
        cert["root_leave"] = root_pair[1]
    return cert


def _norm_realizable(raw: Any) -> Optional[dict[str, dict[str, list[list[str]]]]]:
    if not isinstance(raw, dict):
        return None
    out: dict[str, dict[str, list[list[str]]]] = {}
    for type_name, depths in raw.items():
        if not isinstance(depths, dict):
            return None
        out[str(type_name)] = {}
        for depth, pairs in depths.items():
            if not isinstance(pairs, list):
                return None
            cleaned = []
            for pair in pairs:
                if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                    return None
                cleaned.append([str(pair[0]), str(pair[1])])
            cleaned.sort()
            out[str(type_name)][str(depth)] = cleaned
    return out


def parse_certificate(raw: Any) -> tuple[Optional[dict[str, Any]], str]:
    if not isinstance(raw, dict):
        return None, "certificate is not a dict"
    status = raw.get("status")
    if status not in ("sat", "unsat"):
        return None, "status must be 'sat' or 'unsat'"
    realizable = _norm_realizable(raw.get("realizable"))
    if realizable is None:
        return None, "realizable summaries are missing or malformed"
    cert: dict[str, Any] = {"status": status, "realizable": realizable}
    if status == "sat":
        if "root_enter" not in raw or "root_leave" not in raw:
            return None, "sat certificate needs root_enter and root_leave"
        cert["root_enter"] = str(raw["root_enter"])
        cert["root_leave"] = str(raw["root_leave"])
    return cert, ""


def verify_certificate(grammar: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    cert, err = parse_certificate(raw)
    if cert is None:
        return False, err
    true = compact_summaries(grammar)
    if cert["realizable"] != true:
        return False, "realizable summaries do not match the independent oracle"
    accepted = root_accepted_pairs(grammar, true)
    sat = bool(accepted)
    if cert["status"] == "sat":
        if not sat:
            return False, "status sat but the grammar is unsatisfiable"
        pair = (cert["root_enter"], cert["root_leave"])
        if pair not in accepted:
            return False, "root pair is not a closed realisable interface"
        return True, "ok"
    if sat:
        return False, "status unsat but a closed realisable root pair exists"
    return True, "ok"


def expand_grammar(
    grammar: Mapping[str, Any], *, max_depth: int = MAX_EXPAND_DEPTH
) -> dict[str, Any]:
    """Unfold into a region network in type-local labels.

    Default ``max_depth`` is the judge/cross-check cap. Raising it is a
    deliberate measurement or test override; exceeding it is a resource
    failure, not unsat.
    """
    depth = int(grammar["depth"])
    if depth > max_depth:
        raise OracleBudgetExceeded(
            f"refusing to expand depth {depth} (cap {max_depth}); this is not evidence of unsat"
        )
    modules = grammar["modules"]
    regions: dict[str, dict[str, list[str]]] = {}
    overlaps: list[dict[str, Any]] = []

    def add_ports(path: str, type_name: str) -> None:
        labels = list(modules[type_name]["ports_domain"])
        regions[path + "/enter"] = {"domain": labels}
        regions[path + "/leave"] = {"domain": labels}

    def walk(path: str, type_name: str, remaining: int) -> None:
        add_ports(path, type_name)
        spec = modules[type_name]
        if spec["kind"] == "leaf" or remaining == 0:
            overlaps.append(
                {
                    "left": path + "/enter",
                    "right": path + "/leave",
                    "pairs": [list(p) for p in spec["pairs"]],
                }
            )
            return
        left_t, right_t = child_types_at_depth(grammar, remaining)
        wiring = wiring_at_depth(grammar, remaining)
        left_path, right_path = path + "/L", path + "/R"
        walk(left_path, left_t, remaining - 1)
        walk(right_path, right_t, remaining - 1)
        overlaps.append(
            {
                "left": path + "/enter",
                "right": left_path + "/enter",
                "pairs": [list(p) for p in wiring["enter"]],
            }
        )
        overlaps.append(
            {
                "left": left_path + "/leave",
                "right": right_path + "/enter",
                "pairs": [list(p) for p in wiring["mid"]],
            }
        )
        overlaps.append(
            {
                "left": right_path + "/leave",
                "right": path + "/leave",
                "pairs": [list(p) for p in wiring["leave"]],
            }
        )

    walk("root", grammar["root"], depth)
    closing = grammar.get("closing")
    if closing:
        overlaps.append(
            {
                "left": "root/enter",
                "right": "root/leave",
                "pairs": [list(p) for p in closing["pairs"]],
            }
        )
    return {"regions": regions, "overlaps": overlaps}


def _csp_solution(instance: Mapping[str, Any], max_nodes: int = 200_000) -> Optional[dict[str, str]]:
    rids = sorted(instance["regions"])
    domains = {rid: set(instance["regions"][rid]["domain"]) for rid in rids}
    allowed: dict[tuple[str, str], dict[str, set[str]]] = {}
    neighbors: dict[str, set[str]] = {rid: set() for rid in rids}
    for overlap in instance["overlaps"]:
        u, v = overlap["left"], overlap["right"]
        fwd: dict[str, set[str]] = defaultdict(set)
        rev: dict[str, set[str]] = defaultdict(set)
        for a, b in overlap["pairs"]:
            fwd[str(a)].add(str(b))
            rev[str(b)].add(str(a))
        neighbors[u].add(v)
        neighbors[v].add(u)
        allowed[(u, v)] = fwd
        allowed[(v, u)] = rev
    nodes = [0]

    def ac3(dom: dict[str, set[str]]) -> bool:
        queue = deque(allowed)
        while queue:
            u, v = queue.popleft()
            rel = allowed.get((u, v), {})
            keep = {a for a in dom[u] if rel.get(a, set()) & dom[v]}
            if keep != dom[u]:
                if not keep:
                    return False
                dom[u] = keep
                for w in neighbors[u]:
                    if w != v:
                        queue.append((w, u))
        return True

    def search(dom: dict[str, set[str]]) -> Optional[dict[str, str]]:
        nodes[0] += 1
        if nodes[0] > max_nodes:
            raise OracleBudgetExceeded(f"expanded oracle exceeded {max_nodes} nodes")
        if not ac3(dom):
            return None
        unassigned = [rid for rid in rids if len(dom[rid]) > 1]
        if not unassigned:
            return {rid: next(iter(sorted(dom[rid]))) for rid in rids}
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


def expanded_satisfiable(grammar: Mapping[str, Any], max_nodes: int = 200_000) -> bool:
    return _csp_solution(expand_grammar(grammar), max_nodes=max_nodes) is not None


def expanded_root_pairs(grammar: Mapping[str, Any], max_nodes: int = 200_000) -> set[tuple[str, str]]:
    """Enumerate root (enter, leave) pairs accepted by the expanded CSP."""
    instance = expand_grammar(grammar)
    labels = list(instance["regions"]["root/enter"]["domain"])
    accepted: set[tuple[str, str]] = set()
    for e in labels:
        for l in labels:
            regions = {
                rid: {"domain": list(spec["domain"])} for rid, spec in instance["regions"].items()
            }
            regions["root/enter"] = {"domain": [e]}
            regions["root/leave"] = {"domain": [l]}
            pinned = {"regions": regions, "overlaps": instance["overlaps"]}
            if _csp_solution(pinned, max_nodes=max_nodes) is not None:
                accepted.add((e, l))
    return accepted


def _tokens(rng: random.Random, n: int, used: set[str]) -> list[str]:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    out = []
    while len(out) < n:
        tok = "".join(rng.choice(alphabet) for _ in range(5))
        if tok not in used:
            used.add(tok)
            out.append(tok)
    return out


def generate_grammar(
    *,
    depth: int,
    interface_size: int,
    regime: str,
    opacity: str,
    ambiguity: str,
    seed: int,
    mid_delta: int = 0,
) -> dict[str, Any]:
    if depth < 1:
        raise ValueError("depth must be >= 1")
    if interface_size not in PRIMES:
        raise ValueError("interface_size must be one of 3, 5, 7")
    if regime not in VALID_REGIMES:
        raise ValueError(f"unknown regime {regime!r}")
    if opacity not in VALID_OPACITY:
        raise ValueError(f"unknown opacity {opacity!r}")
    if ambiguity not in VALID_AMBIGUITY:
        raise ValueError(f"unknown ambiguity {ambiguity!r}")

    rng = random.Random(seed)
    q = int(interface_size)
    used: set[str] = set()
    if opacity == TRANSPARENT:
        # Shared names so the copy-upward baseline can succeed on identity trees.
        stem = [f"s{i}" for i in range(q)]
        tip = [f"s{i}" for i in range(q)]
        weed = [f"s{i}" for i in range(q)]
    else:
        stem = _tokens(rng, q, used)
        tip = _tokens(rng, q, used)
        weed = _tokens(rng, q, used)

    if regime == TREE:
        leaf_delta = 0
        closing = None
    elif regime == CYCLIC_SAT:
        leaf_delta = 0
        closing = {"pairs": [[stem[i], stem[i]] for i in range(q)]}
    else:
        leaf_delta = 1
        closing = {"pairs": [[stem[i], stem[i]] for i in range(q)]}

    tip_pairs = [[tip[i], tip[(i + leaf_delta) % q]] for i in range(q)]
    weed_pairs = [[weed[i], weed[(i + 2) % q]] for i in range(q)]

    deeper_wiring = {
        "enter": [[stem[i], stem[i]] for i in range(q)],
        "mid": [[stem[i], stem[(i + int(mid_delta)) % q]] for i in range(q)],
        "leave": [[stem[i], stem[i]] for i in range(q)],
    }
    depth1_right = "weed" if ambiguity == DECOY else "tip"
    right_labels = weed if depth1_right == "weed" else tip
    depth1_wiring = {
        "enter": [[stem[i], tip[i]] for i in range(q)],
        "mid": [[tip[i], right_labels[(i + int(mid_delta)) % q]] for i in range(q)],
        "leave": [[right_labels[i], stem[i]] for i in range(q)],
    }

    modules: dict[str, Any] = {
        "stem": {
            "kind": "branch",
            "ports": ["enter", "leave"],
            "ports_domain": list(stem),
        },
        "tip": {
            "kind": "leaf",
            "ports": ["enter", "leave"],
            "ports_domain": list(tip),
            "pairs": tip_pairs,
        },
    }
    if ambiguity == DECOY:
        modules["weed"] = {
            "kind": "leaf",
            "ports": ["enter", "leave"],
            "ports_domain": list(weed),
            "pairs": weed_pairs,
        }

    return {
        "root": "stem",
        "depth": depth,
        "modules": modules,
        "productions": {
            "stem": {
                "deeper": {"left": "stem", "right": "stem", "wiring": deeper_wiring},
                "depth_1": {
                    "left": "tip",
                    "right": depth1_right,
                    "wiring": depth1_wiring,
                },
            }
        },
        "closing": closing,
        "meta": {
            "regime": regime,
            "opacity": opacity,
            "ambiguity": ambiguity,
            "interface_size": q,
            "mid_delta": int(mid_delta),
        },
    }


def relabel_grammar(grammar: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Presentation twin: permute each type's labels. Answer preserved."""
    rng = random.Random(seed)
    modules = grammar["modules"]
    mapping: dict[str, dict[str, str]] = {}
    used: set[str] = set()
    new_modules: dict[str, Any] = {}
    for name, spec in modules.items():
        local = {}
        new_domain = []
        for old in spec["ports_domain"]:
            tok = _tokens(rng, 1, used)[0]
            local[old] = tok
            new_domain.append(tok)
        mapping[name] = local
        new_spec = dict(spec)
        new_spec["ports_domain"] = new_domain
        if spec["kind"] == "leaf":
            new_spec["pairs"] = [[local[a], local[b]] for a, b in spec["pairs"]]
        new_modules[name] = new_spec

    def remap_wiring(wiring: Mapping[str, list], left_t: str, right_t: str) -> dict:
        sm, lm, rm = mapping["stem"], mapping[left_t], mapping[right_t]
        return {
            "enter": [[sm[a], lm[b]] for a, b in wiring["enter"]],
            "mid": [[lm[a], rm[b]] for a, b in wiring["mid"]],
            "leave": [[rm[a], sm[b]] for a, b in wiring["leave"]],
        }

    prod = grammar["productions"]["stem"]
    new_prod = {
        "deeper": {
            "left": prod["deeper"]["left"],
            "right": prod["deeper"]["right"],
            "wiring": remap_wiring(
                prod["deeper"]["wiring"], prod["deeper"]["left"], prod["deeper"]["right"]
            ),
        },
        "depth_1": {
            "left": prod["depth_1"]["left"],
            "right": prod["depth_1"]["right"],
            "wiring": remap_wiring(
                prod["depth_1"]["wiring"], prod["depth_1"]["left"], prod["depth_1"]["right"]
            ),
        },
    }
    closing = grammar.get("closing")
    new_closing = None
    if closing:
        sm = mapping["stem"]
        new_closing = {"pairs": [[sm[a], sm[b]] for a, b in closing["pairs"]]}
    return {
        "root": grammar["root"],
        "depth": grammar["depth"],
        "modules": new_modules,
        "productions": {"stem": new_prod},
        "closing": new_closing,
        "meta": dict(grammar.get("meta") or {}),
    }


def example_visible_grammar() -> dict[str, Any]:
    """Depth-1 tree, identity tip. Copy-upward baseline succeeds on this case."""
    return generate_grammar(
        depth=1,
        interface_size=3,
        regime=TREE,
        opacity=TRANSPARENT,
        ambiguity=CLEAN,
        seed=0,
    )


def arm_compact(grammar: Mapping[str, Any]) -> dict[str, Any]:
    """Reference solver: compact summaries. Agent-facing success condition."""
    return reference_certificate(grammar)


def arm_expanded(grammar: Mapping[str, Any]) -> dict[str, Any]:
    """Cross-check: independent expanded SAT, then the compact certificate.

    SAT is decided by the expanded CSP. The compact ``realizable`` tables are
    not computed by expansion; filling the exact-match certificate still uses
    the compact oracle. The scaling experiment never calls this function.
    """
    sat = expanded_satisfiable(grammar)
    cert = reference_certificate(grammar)
    if sat != (cert["status"] == "sat"):
        raise RuntimeError("expanded SAT disagrees with compact SAT")
    return cert


def arm_given_canonical(grammar: Mapping[str, Any]) -> dict[str, Any]:
    """Placeholder for a future revealed-coordinates condition.

    Currently identical to ``arm_compact``. It is not a distinct implemented
    solver and has not been run as a model-facing experimental arm.
    """
    return reference_certificate(grammar)


def arm_copy_leaf_upward(grammar: Mapping[str, Any]) -> dict[str, Any]:
    """Naive baseline: copy tip pairs onto every type and remaining depth."""
    depth = int(grammar["depth"])
    tip_pairs = [list(p) for p in grammar["modules"]["tip"]["pairs"]]
    realizable = {}
    for name, spec in grammar["modules"].items():
        if spec["kind"] == "leaf":
            pairs = [list(p) for p in spec["pairs"]]
            realizable[name] = {"0": pairs}
        else:
            realizable[name] = {str(k): [list(p) for p in tip_pairs] for k in range(1, depth + 1)}
    return {
        "status": "sat",
        "realizable": realizable,
        "root_enter": tip_pairs[0][0],
        "root_leave": tip_pairs[0][1],
    }


def local_tables_nonempty(grammar: Mapping[str, Any]) -> bool:
    for spec in grammar["modules"].values():
        if not spec.get("ports_domain"):
            return False
        if spec["kind"] == "leaf" and not spec.get("pairs"):
            return False
    prod = grammar["productions"]["stem"]
    for block in (prod["deeper"], prod["depth_1"]):
        for table in block["wiring"].values():
            if not table:
                return False
    closing = grammar.get("closing")
    if closing is not None and not closing.get("pairs"):
        return False
    return True


def evaluate_solver(solve_fn: Callable[[dict[str, Any]], Any], grammar: dict[str, Any]) -> bool:
    import copy

    try:
        raw = solve_fn(copy.deepcopy(public_grammar(grammar)))
    except Exception:
        return False
    ok, _reason = verify_certificate(grammar, raw)
    return ok


def build_grade_grammars(
    *,
    depth: int,
    interface_size: int,
    regime: str,
    opacity: str,
    ambiguity: str,
    seed: int,
) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_grammar(
        depth=depth,
        interface_size=interface_size,
        regime=regime,
        opacity=opacity,
        ambiguity=ambiguity,
        seed=seed,
    )
    return [
        ("local_visible", example_visible_grammar()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_grammar(
                depth=max(depth, 2),
                interface_size=interface_size,
                regime=CYCLIC_SAT,
                opacity=opacity,
                ambiguity=CLEAN,
                seed=seed + 11,
            ),
        ),
        (
            "assembled_unsat",
            generate_grammar(
                depth=max(depth, 2),
                interface_size=interface_size,
                regime=CYCLIC_UNSAT,
                opacity=opacity,
                ambiguity=CLEAN,
                seed=seed + 13,
            ),
        ),
        ("opaque_twin", relabel_grammar(configured, seed + 99)),
        (
            "decoy_heldout",
            generate_grammar(
                depth=max(depth, 1),
                interface_size=interface_size,
                regime=regime if regime != TREE else CYCLIC_SAT,
                opacity=opacity,
                ambiguity=DECOY,
                seed=seed + 17,
            ),
        ),
        (
            "heldout_twist",
            generate_grammar(
                depth=max(depth, 2),
                interface_size=interface_size,
                regime=CYCLIC_SAT,
                opacity=OPAQUE,
                ambiguity=CLEAN,
                seed=seed + 19,
                mid_delta=1,
            ),
        ),
    ]


def grade_solver(
    solve_fn: Callable[[dict[str, Any]], Any],
    *,
    depth: int,
    interface_size: int,
    regime: str,
    opacity: str,
    ambiguity: str,
    seed: int,
) -> dict[str, bool]:
    import copy

    items = build_grade_grammars(
        depth=depth,
        interface_size=interface_size,
        regime=regime,
        opacity=opacity,
        ambiguity=ambiguity,
        seed=seed,
    )
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, grammar in items:
        checks[name] = evaluate_solver(solve_fn, grammar)
    configured = named["configured"]
    try:
        pub = public_grammar(configured)
        first = solve_fn(copy.deepcopy(pub))
        second = solve_fn(copy.deepcopy(pub))
        ok, _ = verify_certificate(configured, first)
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks


def measure_scaling(
    interface_size: int = 5, regime: str = CYCLIC_UNSAT, seed: int = 0
) -> list[dict[str, Any]]:
    rows = []
    for depth in (1, 2, 3, 4, 6, 12):
        grammar = generate_grammar(
            depth=depth,
            interface_size=interface_size,
            regime=regime,
            opacity=OPAQUE,
            ambiguity=CLEAN,
            seed=seed,
        )
        t0 = time.perf_counter()
        cert = reference_certificate(grammar)
        compact_ms = (time.perf_counter() - t0) * 1000.0
        expanded_ms = None
        if depth <= 4:
            t1 = time.perf_counter()
            expanded_sat = expanded_satisfiable(grammar)
            expanded_ms = (time.perf_counter() - t1) * 1000.0
            if expanded_sat != (cert["status"] == "sat"):
                raise RuntimeError(f"scaling cross-check failed at depth {depth}")
        rows.append(
            {
                "depth": depth,
                "occurrences": unfolded_occurrences(depth),
                "leaves": unfolded_leaves(depth),
                "compact_bytes": compact_input_bytes(grammar),
                "summary_cells": summary_cells(cert["realizable"]),
                "compact_ms": round(compact_ms, 3),
                "expanded_ms": None if expanded_ms is None else round(expanded_ms, 3),
                "status": cert["status"],
            }
        )
    return rows
