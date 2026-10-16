"""Nested finite coordinate maps.

Each module carries a finite state set and an in-to-out transition from one
declared family (multiplicative on F_p^x, affine on F_p, or a listed
permutation). A parent transition is the composition of its children's
transitions. A cycle is compatible when some state returns to itself after
every map in documented order.

Raw point-assignments glue uniquely. Constrained transitions need not have a
state that survives the cycle: that is an empty solution set, not a failure of
the unrestricted sheaf axiom.

This module is the trusted oracle. It does not import the candidate solver.
"""
from __future__ import annotations

import copy
import random
from typing import Any, Callable, Mapping, Optional


MUL = "multiplicative"
AFF = "affine"
PERM = "permutation"
DIRECT = "direct"
RECURSIVE = "recursive"
FLAT = "flat"
REC_COMP = "recursive_composition"
REVEALED = "revealed"
INFERRED = "inferred"
PUBLIC_KEYS = (
    "family",
    "modulus",
    "domain",
    "modules",
    "root",
    "depth",
    "cycle",
    "calibration",
    "representation",
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
    """Resource overrun. This is not evidence that no compatible state exists."""


def public_instance(inst: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: copy.deepcopy(inst[key]) for key in PUBLIC_KEYS}
    if inst.get("representation") == REVEALED:
        out["maps"] = copy.deepcopy(inst["maps"])
    if inst.get("representation") == "explicit":
        out["maps"] = copy.deepcopy(inst["maps"])
        out["expanded"] = copy.deepcopy(inst["expanded"])
    return out


def _inv_mod(x: int, p: int) -> int:
    return pow(int(x) % p, p - 2, p)


def apply_spec(family: str, spec: Mapping[str, Any], x: int, modulus: int) -> int:
    if family == MUL:
        return (int(spec["q"]) * int(x)) % modulus
    if family == AFF:
        return (int(spec["a"]) * int(x) + int(spec["b"])) % modulus
    if family == PERM:
        image = spec["image"]
        return int(image[int(x)])
    raise ValueError(family)


def compose_specs(family: str, specs: list[Mapping[str, Any]], modulus: int) -> dict[str, Any]:
    """Compose f_{n-1} ∘ ... ∘ f_0 (f_0 applied first)."""
    if family == MUL:
        q = 1
        for spec in specs:
            q = (q * int(spec["q"])) % modulus
        return {"q": q}
    if family == AFF:
        a, b = 1, 0
        for spec in specs:
            a2, b2 = int(spec["a"]), int(spec["b"])
            a, b = (a2 * a) % modulus, (a2 * b + b2) % modulus
        return {"a": a, "b": b}
    if family == PERM:
        n = len(specs[0]["image"])
        image = list(range(n))
        for spec in specs:
            image = [int(spec["image"][x]) for x in image]
        return {"image": image}
    raise ValueError(family)


def fixed_states(family: str, spec: Mapping[str, Any], domain: list[int], modulus: int) -> list[int]:
    return [x for x in domain if apply_spec(family, spec, x, modulus) == x]


def calibrate(family: str, spec: Mapping[str, Any], domain: list[int], modulus: int) -> list[list[int]]:
    if family == MUL:
        x = domain[0]
        return [[x, apply_spec(family, spec, x, modulus)]]
    if family == AFF:
        xs = domain[:2]
        return [[x, apply_spec(family, spec, x, modulus)] for x in xs]
    return [[x, apply_spec(family, spec, x, modulus)] for x in domain]


def infer_from_calibration(family: str, pairs: list, domain: list[int], modulus: int) -> dict[str, Any]:
    if family == MUL:
        x, y = pairs[0]
        return {"q": (int(y) * _inv_mod(int(x), modulus)) % modulus}
    if family == AFF:
        x1, y1 = pairs[0]
        x2, y2 = pairs[1]
        dx = (int(x1) - int(x2)) % modulus
        dy = (int(y1) - int(y2)) % modulus
        a = (dy * _inv_mod(dx, modulus)) % modulus
        b = (int(y1) - a * int(x1)) % modulus
        return {"a": a, "b": b}
    image = [0] * len(domain)
    for x, y in pairs:
        image[int(x)] = int(y)
    return {"image": image}


def maps_equal(family: str, a: Mapping[str, Any], b: Mapping[str, Any], modulus: int) -> bool:
    if family == MUL:
        return int(a["q"]) % modulus == int(b["q"]) % modulus
    if family == AFF:
        return int(a["a"]) % modulus == int(b["a"]) % modulus and int(a["b"]) % modulus == int(b["b"]) % modulus
    return list(a["image"]) == list(b["image"])


def generate_instance(
    *,
    depth: int,
    family: str,
    regime: str,
    representation: str,
    seed: int,
) -> dict[str, Any]:
    if depth < 1:
        raise ValueError("depth")
    rng = random.Random(seed)
    if family == PERM:
        modulus = 4
        domain = list(range(modulus))
    elif family == MUL:
        modulus = 7
        domain = list(range(1, modulus))
    else:
        modulus = 7
        domain = list(range(modulus))

    def mul_spec(q: int) -> dict[str, int]:
        return {"q": int(q) % modulus}

    def aff_spec(a: int, b: int) -> dict[str, int]:
        return {"a": int(a) % modulus, "b": int(b) % modulus}

    def perm_spec(image: list[int]) -> dict[str, list[int]]:
        return {"image": list(image)}

    identity = {
        MUL: mul_spec(1),
        AFF: aff_spec(1, 0),
        PERM: perm_spec(list(domain)),
    }[family]
    twist = {
        MUL: mul_spec(3),
        AFF: aff_spec(1, 1),  # translation, no fixed point
        PERM: perm_spec([(i + 1) % modulus for i in domain]),  # derangement
    }[family]
    sat_twist = {
        MUL: mul_spec(1),
        AFF: aff_spec(2, 1),  # unique fixed point
        PERM: perm_spec([1, 0, 2, 3] if modulus == 4 else list(domain)),
    }[family]

    leaf_map = identity
    root_extra = identity
    sat = True
    if regime in (DIRECT, FLAT):
        depth_used = 1
        if regime == FLAT:
            # three maps in a cycle; SAT uses sat_twist as one factor that still has a fp
            leaf_map = sat_twist if family != MUL else mul_spec(1)
            root_extra = identity
            sat = True
        else:
            leaf_map = identity
            sat = True
    elif regime == RECURSIVE:
        depth_used = max(depth, 2)
        leaf_map = identity
        root_extra = sat_twist if family != MUL else identity
        sat = True
    else:  # REC_COMP: each child has a fixed state, the nested cycle does not
        depth_used = max(depth, 2)
        leaf_map = identity
        root_extra = twist
        sat = False

    modules = {
        "leaf": {"ports": ["in", "out"], "child": None},
        "node": {"ports": ["in", "out"], "child": "leaf"},
    }
    root = "leaf" if depth_used == 1 else "node"
    maps = {"leaf": leaf_map, "node_extra": root_extra}

    # Cycle: apply leaf (depth times if nested) then node_extra.
    cycle = []
    if root == "leaf":
        cycle = ["leaf"]
        if regime == FLAT:
            cycle = ["leaf", "leaf", "node_extra"]
            maps["node_extra"] = identity
    else:
        cycle = ["leaf"] * depth_used + ["node_extra"]

    expanded = [copy.deepcopy(maps[name]) for name in cycle]
    composite = compose_specs(family, expanded, modulus)
    fps = fixed_states(family, composite, domain, modulus)
    sat = bool(fps)

    calibration = {name: calibrate(family, spec, domain, modulus) for name, spec in maps.items()}
    inst = {
        "family": family,
        "modulus": modulus,
        "domain": domain,
        "modules": modules,
        "root": root,
        "depth": depth_used,
        "cycle": cycle,
        "calibration": calibration,
        "representation": representation,
        "maps": maps,
        "expanded": expanded,
        "meta": {"regime": regime, "sat": sat, "seed": seed, "composite": composite, "fixed": fps},
    }
    return inst


def expand_instance(inst: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [copy.deepcopy(inst["maps"][name]) for name in inst["cycle"]]


def composite_of(inst: Mapping[str, Any]) -> dict[str, Any]:
    return compose_specs(inst["family"], expand_instance(inst), int(inst["modulus"]))


def instance_satisfiable(inst: Mapping[str, Any], budget: int = 50_000) -> bool:
    budget_box = [budget]
    family, modulus, domain = inst["family"], int(inst["modulus"]), list(inst["domain"])
    spec = composite_of(inst)
    found = []
    for x in domain:
        budget_box[0] -= 1
        if budget_box[0] < 0:
            raise OracleBudgetExceeded("map oracle exceeded step budget; refusing to call this unsat")
        if apply_spec(family, spec, x, modulus) == x:
            found.append(x)
    return bool(found)


def relabel_instance(inst: Mapping[str, Any], seed: int) -> dict[str, Any]:
    """Presentation twin: family-preserving change of coordinates."""
    rng = random.Random(seed)
    domain = list(inst["domain"])
    family, modulus = inst["family"], int(inst["modulus"])
    if family == MUL:
        scale = rng.choice(domain)
        fwd = {old: (scale * old) % modulus for old in domain}
    elif family == AFF:
        scale = rng.choice(range(1, modulus))
        shift = rng.choice(range(modulus))
        fwd = {old: (scale * old + shift) % modulus for old in domain}
    else:
        shuffled = list(domain)
        rng.shuffle(shuffled)
        fwd = {old: new for old, new in zip(domain, shuffled)}
    back = {new: old for old, new in fwd.items()}

    def transport(spec: Mapping[str, Any]) -> dict[str, Any]:
        pairs = []
        sample = domain if family == PERM else (domain[:2] if family == AFF else domain[:1])
        for new_x in sample:
            old_x = back[new_x]
            old_y = apply_spec(family, spec, old_x, modulus)
            pairs.append([new_x, fwd[old_y]])
        if family == PERM:
            image = [0] * len(domain)
            for new_x in domain:
                old_x = back[new_x]
                image[new_x] = fwd[apply_spec(family, spec, old_x, modulus)]
            return {"image": image}
        return infer_from_calibration(family, pairs, domain, modulus)

    maps = {name: transport(spec) for name, spec in inst["maps"].items()}
    foil = copy.deepcopy(inst)
    foil["maps"] = maps
    foil["calibration"] = {name: calibrate(family, spec, domain, modulus) for name, spec in maps.items()}
    foil["expanded"] = [copy.deepcopy(maps[name]) for name in foil["cycle"]]
    foil["domain"] = domain
    foil["meta"] = dict(inst.get("meta") or {})
    foil["meta"]["relabel"] = True
    return foil


def example_visible_instance() -> dict[str, Any]:
    return generate_instance(
        depth=1, family=MUL, regime=DIRECT, representation=REVEALED, seed=0
    )


def reference_certificate(inst: Mapping[str, Any]) -> dict[str, Any]:
    family, modulus, domain = inst["family"], int(inst["modulus"]), list(inst["domain"])
    spec = composite_of(inst)
    fps = fixed_states(family, spec, domain, modulus)
    if not fps:
        return {"status": "unsat"}
    return {
        "status": "sat",
        "state": int(fps[0]),
        "maps": copy.deepcopy(inst["maps"]),
    }


def _require_status(raw: Any) -> tuple[Optional[str], str]:
    if not isinstance(raw, dict):
        return None, "not a dict"
    status = raw.get("status")
    if status not in ("sat", "unsat"):
        return None, "status"
    return status, ""


def verify_certificate(inst: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    """Independent of the candidate solver. Uses composition + enumeration."""
    status, err = _require_status(raw)
    if err:
        return False, err
    true_sat = instance_satisfiable(inst)
    if status == "unsat":
        return (not true_sat, "unsat but a compatible state exists" if true_sat else "ok")
    if not true_sat:
        return False, "sat but no compatible state exists"
    if "state" not in raw:
        return False, "sat needs state"
    try:
        state = int(raw["state"])
    except (TypeError, ValueError):
        return False, "state"
    if state not in inst["domain"]:
        return False, "state not in domain"
    submitted_maps = raw.get("maps")
    if inst.get("representation") == INFERRED:
        if not isinstance(submitted_maps, dict):
            return False, "inferred maps missing"
        for name, pairs in inst["calibration"].items():
            if name not in submitted_maps:
                return False, f"map {name} missing"
            inferred = infer_from_calibration(inst["family"], pairs, inst["domain"], int(inst["modulus"]))
            if not maps_equal(inst["family"], submitted_maps[name], inferred, int(inst["modulus"])):
                return False, f"map {name} disagrees with calibration"
        spec = compose_specs(
            inst["family"],
            [submitted_maps[name] for name in inst["cycle"]],
            int(inst["modulus"]),
        )
    else:
        spec = composite_of(inst)
    if apply_spec(inst["family"], spec, state, int(inst["modulus"])) != state:
        return False, "state is not compatible with the cycle"
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
    """Baseline: nonempty domain => sat, ignore the cycle."""
    return {"status": "sat", "state": int(inst["domain"][0]), "maps": copy.deepcopy(inst.get("maps") or {})}


def arm_revealed_compose(inst: Mapping[str, Any]) -> dict[str, Any]:
    if inst.get("representation") == INFERRED and "maps" not in public_instance(inst):
        return arm_local_only(inst)
    return reference_certificate(inst)


def build_grade_items(
    *, depth: int, family: str, regime: str, representation: str, seed: int
) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_instance(
        depth=depth, family=family, regime=regime, representation=representation, seed=seed
    )
    explicit = generate_instance(
        depth=depth, family=family, regime=regime, representation="explicit", seed=seed
    )
    return [
        ("local_visible", example_visible_instance()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_instance(
                depth=max(depth, 1),
                family=family,
                regime=RECURSIVE,
                representation=representation,
                seed=seed + 11,
            ),
        ),
        (
            "assembled_unsat",
            generate_instance(
                depth=max(depth, 2),
                family=family,
                regime=REC_COMP,
                representation=representation,
                seed=seed + 13,
            ),
        ),
        ("opaque_twin", relabel_instance(configured, seed + 99)),
        ("explicit_expand", explicit),
    ]


def grade_solver(
    solve_fn: Callable,
    *,
    depth: int,
    family: str,
    regime: str,
    representation: str,
    seed: int,
) -> dict[str, bool]:
    items = build_grade_items(
        depth=depth, family=family, regime=regime, representation=representation, seed=seed
    )
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
