"""Finite region-network instances, recursive generator, and independent oracle.

Mathematical contract
---------------------
An instance is a finite binary constraint network:

* Each region i has a finite domain D_i of local state labels.
* Each overlap between regions i and j is a relation R_ij ⊆ D_i × D_j.
* An assignment x is valid iff x_i ∈ D_i for every i and (x_i, x_j) ∈ R_ij
  for every overlap.

The generator builds the network by recursively substituting a two-child
branch template into itself. Hidden structure is a value in Z/nZ on each
region plus a local labelling of that carrier. Observable overlaps are the
translation relations of those hidden values. A cyclic regime either closes
those translations consistently (satisfiable) or introduces a single cycle
whose translations cannot compose to the identity (unsatisfiable), while
every individual domain and every individual overlap remains nonempty.
Satisfiable instances pin one leaf domain to the true hidden label so a
greedy first-value walk does not accidentally hit a solution.

The oracle is a general finite-domain CSP solver (AC-3 then MRV backtracking).
It sees only the observable instance. It never consults the hidden carrier,
the candidate solver, or a timeout: exceeding the node budget raises
OracleBudgetExceeded rather than reporting unsatisfiability.
"""
from __future__ import annotations

import random
from collections import defaultdict, deque
from typing import Any, Callable, Mapping, Optional


TREE = "tree"
CYCLIC_SAT = "cyclic_sat"
CYCLIC_UNSAT = "cyclic_unsat"
TRANSPARENT = "transparent"
OPAQUE = "opaque"
VALID_REGIMES = (TREE, CYCLIC_SAT, CYCLIC_UNSAT)
VALID_LABEL_MODES = (TRANSPARENT, OPAQUE)

CHECK_NAMES = (
    "local_path_sat",
    "configured",
    "solvable_cycle",
    "obstructed_cycle",
    "nested_recursive",
    "cyclic_sat_generated",
    "cyclic_unsat_generated",
    "relabel_twin",
    "heldout_large",
    "branching_sat",
    "branching_unsat",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Search exceeded its node budget. This is not evidence of unsatisfiability."""


# ---------------------------------------------------------------------------
# Instance accessors
# ---------------------------------------------------------------------------

def region_ids(instance: Mapping[str, Any]) -> list[str]:
    return sorted(instance["regions"])


def domain_of(instance: Mapping[str, Any], rid: str) -> list[str]:
    return list(instance["regions"][rid]["domain"])


def overlap_pairs(overlap: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [(str(a), str(b)) for a, b in overlap["pairs"]]


def max_name_depth(instance: Mapping[str, Any]) -> int:
    if not instance["regions"]:
        return 0
    return max(rid.count("/") for rid in instance["regions"])


def region_count(instance: Mapping[str, Any]) -> int:
    return len(instance["regions"])


def overlap_count(instance: Mapping[str, Any]) -> int:
    return len(instance["overlaps"])


def cartesian_size(instance: Mapping[str, Any]) -> int:
    size = 1
    for spec in instance["regions"].values():
        size *= max(len(spec["domain"]), 1)
    return size


def undirected_edges(instance: Mapping[str, Any]) -> list[tuple[str, str]]:
    edges = []
    seen: set[tuple[str, str]] = set()
    for overlap in instance["overlaps"]:
        left, right = str(overlap["left"]), str(overlap["right"])
        key = (left, right) if left <= right else (right, left)
        if key not in seen:
            seen.add(key)
            edges.append(key)
    return edges


def has_undirected_cycle(instance: Mapping[str, Any]) -> bool:
    parent: dict[str, Optional[str]] = {}

    def find(node: str) -> str:
        while parent[node] is not None:
            node = parent[node]
        return node

    for rid in instance["regions"]:
        parent[rid] = None
    for left, right in undirected_edges(instance):
        a, b = find(left), find(right)
        if a == b:
            return True
        parent[a] = b
    return False


def has_skip_level_overlap(instance: Mapping[str, Any]) -> bool:
    for overlap in instance["overlaps"]:
        left, right = str(overlap["left"]), str(overlap["right"])
        if abs(left.count("/") - right.count("/")) > 1:
            return True
    return False


def pairwise_nonempty(instance: Mapping[str, Any]) -> bool:
    if any(len(spec["domain"]) == 0 for spec in instance["regions"].values()):
        return False
    return all(len(overlap["pairs"]) > 0 for overlap in instance["overlaps"])


def semantic_issues(instance: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if not isinstance(instance, Mapping):
        return ["instance is not a mapping"]
    regions = instance.get("regions")
    overlaps = instance.get("overlaps")
    if not isinstance(regions, Mapping) or not regions:
        issues.append("regions must be a nonempty mapping")
        return issues
    if not isinstance(overlaps, list):
        issues.append("overlaps must be a list")
        return issues
    for rid, spec in regions.items():
        if not isinstance(rid, str) or not rid:
            issues.append("region ids must be nonempty strings")
            continue
        if not isinstance(spec, Mapping) or "domain" not in spec:
            issues.append(f"region {rid!r} missing domain")
            continue
        domain = spec["domain"]
        if not isinstance(domain, list) or not domain:
            issues.append(f"region {rid!r} has an empty domain")
            continue
        if len(domain) != len(set(domain)):
            issues.append(f"region {rid!r} has duplicate labels")
        if not all(isinstance(label, str) and label for label in domain):
            issues.append(f"region {rid!r} has a non-string label")
    known = set(regions)
    for index, overlap in enumerate(overlaps):
        if not isinstance(overlap, Mapping):
            issues.append(f"overlap {index} is not a mapping")
            continue
        left, right = overlap.get("left"), overlap.get("right")
        if left not in known or right not in known:
            issues.append(f"overlap {index} refers to a missing region")
            continue
        left_dom = set(regions[left]["domain"])
        right_dom = set(regions[right]["domain"])
        pairs = overlap.get("pairs")
        if not isinstance(pairs, list):
            issues.append(f"overlap {index} pairs must be a list")
            continue
        seen_pairs: set[tuple[str, str]] = set()
        for pair in pairs:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                issues.append(f"overlap {index} has a malformed pair")
                continue
            a, b = str(pair[0]), str(pair[1])
            if a not in left_dom or b not in right_dom:
                issues.append(f"overlap {index} pair {(a, b)} leaves a domain")
            if (a, b) in seen_pairs:
                issues.append(f"overlap {index} has a duplicate pair")
            seen_pairs.add((a, b))
    return issues


def is_semantically_valid(instance: Mapping[str, Any]) -> bool:
    return not semantic_issues(instance)


# ---------------------------------------------------------------------------
# Hand-built examples
# ---------------------------------------------------------------------------

def example_solvable_cycle() -> dict[str, Any]:
    """Three same-level regions, equality around a cycle: globally satisfiable.

    Every neighbouring pair is compatible (the identity relation). The two
    global assignments are the constant maps to "0" and to "1".
    """
    eq = [["0", "0"], ["1", "1"]]
    return {
        "regions": {
            "cell_a": {"domain": ["0", "1"]},
            "cell_b": {"domain": ["0", "1"]},
            "cell_c": {"domain": ["0", "1"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": eq},
            {"left": "cell_b", "right": "cell_c", "pairs": eq},
            {"left": "cell_c", "right": "cell_a", "pairs": eq},
        ],
    }


def example_obstructed_cycle() -> dict[str, Any]:
    """Three same-level regions, inequality around a triangle.

    Each domain is nonempty and each neighbouring pair has a compatible
    joint state, but no assignment satisfies all three overlaps at once.
    """
    neq = [["0", "1"], ["1", "0"]]
    return {
        "regions": {
            "cell_a": {"domain": ["0", "1"]},
            "cell_b": {"domain": ["0", "1"]},
            "cell_c": {"domain": ["0", "1"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": neq},
            {"left": "cell_b", "right": "cell_c", "pairs": neq},
            {"left": "cell_c", "right": "cell_a", "pairs": neq},
        ],
    }


def example_local_path_sat() -> dict[str, Any]:
    """Two same-level regions with a unique compatible pair, used as a visible case."""
    return {
        "regions": {
            "cell_a": {"domain": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"]]},
        ],
    }


def example_three_line_sat() -> dict[str, Any]:
    """Three same-level regions in a path. First-domain greedy succeeds."""
    return {
        "regions": {
            "cell_a": {"domain": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"]},
            "cell_c": {"domain": ["t", "u"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]},
            {"left": "cell_b", "right": "cell_c", "pairs": [["r", "t"], ["s", "u"]]},
        ],
    }


# ---------------------------------------------------------------------------
# Recursive generator
# ---------------------------------------------------------------------------

def _opaque_label(rng: Any, used: set[str]) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while True:
        token = "".join(rng.choice(alphabet) for _ in range(5))
        if token not in used:
            used.add(token)
            return token


def generate_instance(
    *,
    depth: int,
    domain_size: int,
    regime: str,
    label_mode: str,
    seed: int,
) -> dict[str, Any]:
    """Assemble a region network by recursive substitution of a branch template.

    ``depth`` is the number of substitution steps (1 = root plus two children).
    It changes the constraint graph: region count is 2**(depth+1)-1, nested
    ids gain a slash per level, and cyclic regimes at depth >= 2 add a
    skip-level overlap from the root to a deep leaf.
    """
    if depth < 1:
        raise ValueError("depth must be >= 1")
    if domain_size < 2:
        raise ValueError("domain_size must be >= 2")
    if regime not in VALID_REGIMES:
        raise ValueError(f"unknown regime {regime!r}")
    if label_mode not in VALID_LABEL_MODES:
        raise ValueError(f"unknown label_mode {label_mode!r}")

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
    regions: dict[str, dict[str, list[str]]] = {}
    for rid in sorted(hidden):
        if label_mode == TRANSPARENT:
            labels_by_hidden = [f"v{i}" for i in range(n)]
        else:
            used: set[str] = set()
            labels_by_hidden = [_opaque_label(label_rng, used) for _ in range(n)]
        frames[rid] = labels_by_hidden
        domain = list(labels_by_hidden)
        label_rng.shuffle(domain)
        regions[rid] = {"domain": domain}

    # Root's first domain value is not its true hidden label, so a greedy
    # first-value walk is not already sitting on the pinned solution.
    root_true = frames["root"][hidden["root"]]
    root_domain = regions["root"]["domain"]
    if root_domain[0] == root_true and len(root_domain) > 1:
        root_domain[0], root_domain[1] = root_domain[1], root_domain[0]

    def translation_pairs(u: str, v: str, delta: int) -> list[list[str]]:
        pairs = []
        for i in range(n):
            pairs.append([frames[u][i], frames[v][(i + delta) % n]])
        return pairs

    def true_delta(u: str, v: str) -> int:
        return (hidden[v] - hidden[u]) % n

    overlaps: list[dict[str, Any]] = []
    for rid in hidden:
        for suffix in ("/L", "/R"):
            child = rid + suffix
            if child not in hidden:
                continue
            delta = true_delta(rid, child)
            overlaps.append(
                {
                    "left": rid,
                    "right": child,
                    "pairs": translation_pairs(rid, child, delta),
                }
            )

    if regime in (CYCLIC_SAT, CYCLIC_UNSAT):
        for rid in hidden:
            left, right = rid + "/L", rid + "/R"
            if left not in hidden or right not in hidden:
                continue
            if regime == CYCLIC_UNSAT and rid == "root":
                delta = (true_delta(left, right) + 1) % n
            else:
                delta = true_delta(left, right)
            overlaps.append(
                {
                    "left": left,
                    "right": right,
                    "pairs": translation_pairs(left, right, delta),
                }
            )
        deep = "root" + "/L" * depth
        if depth >= 2 and deep in hidden:
            overlaps.append(
                {
                    "left": "root",
                    "right": deep,
                    "pairs": translation_pairs("root", deep, true_delta("root", deep)),
                }
            )

    # Pin both polarities identically: domain sizes must not reveal the verdict.
    leaf = "root" + "/R" * depth
    true_leaf = frames[leaf][hidden[leaf]]
    regions[leaf]["domain"] = regions[leaf]["domain"][:1]
    regions[leaf]["domain"][0] = true_leaf

    for overlap in overlaps:
        left_dom = set(regions[overlap["left"]]["domain"])
        right_dom = set(regions[overlap["right"]]["domain"])
        overlap["pairs"] = [
            [a, b] for a, b in overlap["pairs"] if a in left_dom and b in right_dom
        ]

    instance = {"regions": regions, "overlaps": overlaps}
    issues = semantic_issues(instance)
    if issues:
        raise RuntimeError("generator produced an invalid instance: " + "; ".join(issues))
    return instance


def relabel_instance(instance: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Apply an independent local relabelling. Satisfiability is preserved."""
    rng = random.Random(seed)
    mapping: dict[str, dict[str, str]] = {}
    new_regions: dict[str, dict[str, list[str]]] = {}
    for rid, spec in instance["regions"].items():
        used: set[str] = set()
        local = {}
        new_domain = []
        for old in spec["domain"]:
            token = _opaque_label(rng, used)
            local[old] = token
            new_domain.append(token)
        mapping[rid] = local
        new_regions[rid] = {"domain": new_domain}
    new_overlaps = []
    for overlap in instance["overlaps"]:
        left, right = overlap["left"], overlap["right"]
        lm, rm = mapping[left], mapping[right]
        pairs = [[lm[a], rm[b]] for a, b in overlap_pairs(overlap)]
        new_overlaps.append({"left": left, "right": right, "pairs": pairs})
    return {"regions": new_regions, "overlaps": new_overlaps}


# ---------------------------------------------------------------------------
# Independent oracle
# ---------------------------------------------------------------------------

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
        left, right = overlap["left"], overlap["right"]
        pairs = set(overlap_pairs(overlap))
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
        fwd: dict[str, set[str]] = defaultdict(set)
        rev: dict[str, set[str]] = defaultdict(set)
        for a, b in overlap_pairs(overlap):
            fwd[a].add(b)
            rev[b].add(a)
        neighbors[u].add(v)
        neighbors[v].add(u)
        if (u, v) in allowed:
            allowed[(u, v)] = {
                key: allowed[(u, v)].get(key, set()) & fwd.get(key, set())
                for key in set(allowed[(u, v)]) | set(fwd)
            }
            allowed[(v, u)] = {
                key: allowed[(v, u)].get(key, set()) & rev.get(key, set())
                for key in set(allowed[(v, u)]) | set(rev)
            }
        else:
            allowed[(u, v)] = {key: set(val) for key, val in fwd.items()}
            allowed[(v, u)] = {key: set(val) for key, val in rev.items()}
    return allowed, neighbors


def oracle_solution(
    instance: Mapping[str, Any], max_nodes: int = 200_000
) -> Optional[dict[str, str]]:
    """Return one valid assignment, or None if the instance is unsatisfiable.

    Completeness: the supported class is a finite binary CSP. AC-3 is a sound
    filter; backtracking then splits on a remaining domain in lexicographic
    MRV order. Every Cartesian tuple is either pruned by a violated constraint
    or eventually assigned. If a solution exists, some branch finds one; if
    every branch fails, none exists. The procedure never treats a budget
    overrun as unsat.
    """
    issues = semantic_issues(instance)
    if issues:
        raise ValueError("invalid instance: " + "; ".join(issues))
    rids = region_ids(instance)
    domains: dict[str, set[str]] = {rid: set(domain_of(instance, rid)) for rid in rids}
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


def reference_solve(instance: Mapping[str, Any]) -> dict[str, Any]:
    """Correct solver used by tests. Not shipped to the agent workspace."""
    assignment = oracle_solution(instance)
    if assignment is None:
        return {"status": "unsat"}
    return {"status": "sat", "assignment": assignment}


# ---------------------------------------------------------------------------
# Output contract and grading
# ---------------------------------------------------------------------------

def parse_solve_output(
    instance: Mapping[str, Any], raw: Any
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
    ok, reason = validate_assignment(instance, coerced)
    if not ok:
        return None, reason
    return {"status": "sat", "assignment": coerced}, ""


def evaluate_solve_fn(solve_fn: Callable[[dict[str, Any]], Any], instance: dict[str, Any]) -> bool:
    import copy

    sat = oracle_satisfiable(instance)
    try:
        raw = solve_fn(copy.deepcopy(instance))
    except Exception:
        return False
    parsed, err = parse_solve_output(instance, raw)
    if err or parsed is None:
        return False
    if sat:
        return parsed["status"] == "sat"
    return parsed["status"] == "unsat"


def build_grade_instances(
    *,
    depth: int,
    domain_size: int,
    regime: str,
    label_mode: str,
    seed: int,
) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_instance(
        depth=depth,
        domain_size=domain_size,
        regime=regime,
        label_mode=label_mode,
        seed=seed,
    )
    items: list[tuple[str, dict[str, Any]]] = [
        ("local_path_sat", example_local_path_sat()),
        ("configured", configured),
        ("solvable_cycle", example_solvable_cycle()),
        ("obstructed_cycle", example_obstructed_cycle()),
        (
            "nested_recursive",
            generate_instance(
                depth=max(depth, 2),
                domain_size=domain_size,
                regime=TREE,
                label_mode=label_mode,
                seed=seed + 11,
            ),
        ),
        (
            "cyclic_sat_generated",
            generate_instance(
                depth=max(depth, 1),
                domain_size=domain_size,
                regime=CYCLIC_SAT,
                label_mode=label_mode,
                seed=seed + 13,
            ),
        ),
        (
            "cyclic_unsat_generated",
            generate_instance(
                depth=max(depth, 1),
                domain_size=domain_size,
                regime=CYCLIC_UNSAT,
                label_mode=label_mode,
                seed=seed + 17,
            ),
        ),
        ("relabel_twin", relabel_instance(configured, seed + 99)),
        ("branching_sat", MonotoneCycle().generate(depth + 3, seed + 41)),
        ("branching_unsat", MonotoneCycle().generate(depth + 3, seed + 41, 1)),
        (
            "heldout_large",
            generate_instance(
                depth=3,
                domain_size=7,
                regime=regime,
                label_mode=OPAQUE,
                seed=seed + 19,
            ),
        ),
    ]
    return items


class MonotoneCycle:
    """A nonfunctional relation chain with a single closing intervention."""

    def chain(self, count, regions, position=0):
        regions[str(position)] = {"domain": ["0", "1"]}
        if position + 1 == count:
            return ()
        edge = {"left": str(position), "right": str(position + 1),
                "pairs": (("0", "0"), ("0", "1"), ("1", "1"))}
        return (edge,) + self.chain(count, regions, position + 1)

    def generate(self, count, seed, obstructed=0):
        if count < 3:
            raise ValueError("a cycle needs at least three regions")
        regions = {}
        edges = self.chain(count, regions)
        closing = {"left": str(count - 1), "right": "0",
                   "pairs": (("0", "1"),) if obstructed else (("1", "0"),)}
        return relabel_instance({"regions": regions, "overlaps": edges + (closing,)}, seed)


def grade_solver(
    solve_fn: Callable[[dict[str, Any]], Any],
    *,
    depth: int,
    domain_size: int,
    regime: str,
    label_mode: str,
    seed: int,
) -> dict[str, bool]:
    import copy

    items = build_grade_instances(
        depth=depth,
        domain_size=domain_size,
        regime=regime,
        label_mode=label_mode,
        seed=seed,
    )
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, inst in items:
        checks[name] = evaluate_solve_fn(solve_fn, inst)
    configured = named["configured"]
    try:
        first = solve_fn(copy.deepcopy(configured))
        second = solve_fn(copy.deepcopy(configured))
        checks["deterministic"] = first == second and parse_solve_output(configured, first)[0] is not None
    except Exception:
        checks["deterministic"] = False
    if set(checks) != set(CHECK_NAMES):
        raise RuntimeError("grade_solver produced an unexpected check set")
    return checks


def naive_independent_assignment(instance: Mapping[str, Any]) -> dict[str, str]:
    return {rid: spec["domain"][0] for rid, spec in instance["regions"].items()}


def naive_copy_shared_label(instance: Mapping[str, Any]) -> Optional[dict[str, str]]:
    shared: Optional[set[str]] = None
    for spec in instance["regions"].values():
        labels = set(spec["domain"])
        shared = labels if shared is None else shared & labels
    if not shared:
        return None
    pick = sorted(shared)[0]
    return {rid: pick for rid in instance["regions"]}


def naive_spanning_forest_assignment(instance: Mapping[str, Any]) -> dict[str, str]:
    """Assign along a spanning forest, ignoring leftover cycle-closing overlaps."""
    regions = instance["regions"]
    adj: dict[str, list[tuple[str, dict[str, list[str]]]]] = defaultdict(list)
    for overlap in instance["overlaps"]:
        left, right = overlap["left"], overlap["right"]
        fwd: dict[str, list[str]] = defaultdict(list)
        rev: dict[str, list[str]] = defaultdict(list)
        for a, b in overlap_pairs(overlap):
            fwd[a].append(b)
            rev[b].append(a)
        adj[left].append((right, fwd))
        adj[right].append((left, rev))
    assignment: dict[str, str] = {}
    for start in sorted(regions):
        if start in assignment:
            continue
        assignment[start] = regions[start]["domain"][0]
        queue = deque([start])
        while queue:
            u = queue.popleft()
            for v, func in adj[u]:
                if v in assignment:
                    continue
                options = func.get(assignment[u], [])
                if options:
                    assignment[v] = options[0]
                    queue.append(v)
    for rid, spec in regions.items():
        if rid not in assignment:
            assignment[rid] = spec["domain"][0]
    return assignment
