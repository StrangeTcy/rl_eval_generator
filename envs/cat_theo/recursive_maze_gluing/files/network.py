"""Recursive maze gluing: nested tiles, explicit routes, Z/2 holonomy.

A solution is a walk of move/descend/ascend steps, not a pair of boundary
labels. Nested tiles must actually be traversed before the root exit opens.
The independent oracle is BFS on (tile stack, room, orientation, cleared, used edges).
"""
from __future__ import annotations

import copy
import random
from collections import deque
from typing import Any, Callable, Mapping, Optional


TREE = "tree"
CYCLIC_SAT = "cyclic_sat"
CYCLIC_UNSAT = "cyclic_unsat"
TRANSPARENT = "transparent"
OPAQUE = "opaque"
CLEAN = "clean"
DECOY = "decoy"
PUBLIC_KEYS = ("root", "depth", "tiles", "start_orientation", "goal_orientation", "nesting")
CHECK_NAMES = (
    "local_visible",
    "configured",
    "assembled_sat",
    "assembled_unsat",
    "opaque_twin",
    "decoy_heldout",
    "deterministic",
)


class OracleBudgetExceeded(RuntimeError):
    """Resource overrun. This is not evidence of unsatisfiability."""


def public_maze(maze: Mapping[str, Any]) -> dict[str, Any]:
    return {key: maze[key] for key in PUBLIC_KEYS}


def _tokens(rng: random.Random, n: int, used: set[str]) -> list[str]:
    out = []
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while len(out) < n:
        tok = "".join(rng.choice(alphabet) for _ in range(5))
        if tok not in used:
            used.add(tok)
            out.append(tok)
    return out


def _rename_tile(tile: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    def m(name: str) -> str:
        return mapping[name]

    return {
        "rooms": [m(r) for r in tile["rooms"]],
        "entrance": m(tile["entrance"]),
        "exit": m(tile["exit"]),
        "edges": [
            {"from": m(e["from"]), "to": m(e["to"]), "flip": int(e["flip"])}
            for e in tile["edges"]
        ],
        "shafts": [
            {
                "from": m(s["from"]),
                "return": m(s["return"]),
                "child": s["child"],
                "flip": int(s["flip"]),
            }
            for s in (tile.get("shafts") or [])
        ],
    }


def generate_maze(
    *,
    depth: int,
    regime: str,
    opacity: str,
    ambiguity: str,
    seed: int,
) -> dict[str, Any]:
    if depth < 1:
        raise ValueError("depth")
    rng = random.Random(seed)
    used: set[str] = set()

    def names(n: int, fallback: list[str]) -> list[str]:
        if opacity == TRANSPARENT:
            return list(fallback)
        return _tokens(rng, n, used)

    keep_rooms = names(5, ["dock", "a", "b", "c", "door"])
    crypt_rooms = names(3, ["entry", "hall", "exit"])
    pit_rooms = names(3, ["mouth", "drop", "floor"])
    dock, ra, rb, rc, door = keep_rooms
    centry, chall, cexit = crypt_rooms
    pentry, pdrop, pexit = pit_rooms

    cycle_flip = 1 if regime == CYCLIC_UNSAT else 0
    tree_edges = [
        {"from": dock, "to": ra, "flip": 0},
        {"from": ra, "to": rc, "flip": 0},
        {"from": rc, "to": door, "flip": 0},
    ]
    cycle_edges = [
        {"from": dock, "to": ra, "flip": 0},
        {"from": ra, "to": rb, "flip": cycle_flip},
        {"from": rb, "to": rc, "flip": 0},
        {"from": rc, "to": door, "flip": 0},
    ]
    if regime == TREE:
        keep_rooms_used = [dock, ra, rc, door]
        keep_edges = tree_edges
        inner_edges = tree_edges
        inner_rooms = [dock, ra, rc, door]
    else:
        keep_rooms_used = keep_rooms
        keep_edges = cycle_edges
        inner_edges = tree_edges
        inner_rooms = [dock, ra, rc, door]

    crypt = {
        "rooms": crypt_rooms,
        "entrance": centry,
        "exit": cexit,
        "edges": [
            {"from": centry, "to": chall, "flip": 0},
            {"from": chall, "to": cexit, "flip": 0},
        ],
        "shafts": [],
    }
    pit = {
        "rooms": pit_rooms,
        "entrance": pentry,
        "exit": pexit,
        "edges": [
            {"from": pentry, "to": pdrop, "flip": 1},
            {"from": pdrop, "to": pexit, "flip": 0},
        ],
        "shafts": [],
    }
    shafts = [{"from": rc, "return": rc, "child": "crypt", "flip": 0}]
    if ambiguity == DECOY:
        shafts.append({"from": rc, "return": rc, "child": "pit", "flip": 0})

    inner_shafts = [{"from": rc, "return": rc, "child": "crypt", "flip": 0}]
    if ambiguity == DECOY:
        inner_shafts.append({"from": rc, "return": rc, "child": "pit", "flip": 0})
    tiles = {
        "keep": {
            "rooms": keep_rooms_used,
            "entrance": dock,
            "exit": door,
            "edges": keep_edges,
            "shafts": shafts,
        },
        "inner_keep": {
            "rooms": inner_rooms,
            "entrance": dock,
            "exit": door,
            "edges": inner_edges,
            "shafts": inner_shafts,
        },
        "crypt": crypt,
    }
    if ambiguity == DECOY:
        tiles["pit"] = pit
    return {
        "root": "keep",
        "depth": int(depth),
        "tiles": tiles,
        "start_orientation": 0,
        "goal_orientation": 0,
        "nesting": {"deeper": "inner_keep"},
        "meta": {"regime": regime, "opacity": opacity, "ambiguity": ambiguity},
    }


def relabel_maze(maze: Mapping[str, Any], seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    used: set[str] = set()
    tiles = {}
    for name, tile in maze["tiles"].items():
        mapping = {old: _tokens(rng, 1, used)[0] for old in tile["rooms"]}
        tiles[name] = _rename_tile(dict(tile), mapping)
    return {
        "root": maze["root"],
        "depth": maze["depth"],
        "tiles": tiles,
        "start_orientation": maze["start_orientation"],
        "goal_orientation": maze["goal_orientation"],
        "nesting": dict(maze.get("nesting") or {}),
        "meta": dict(maze.get("meta") or {}),
    }


def child_tile(maze: Mapping[str, Any], remaining: int, shaft: Mapping[str, Any]) -> str:
    if remaining <= 1:
        return shaft["child"]
    return str((maze.get("nesting") or {}).get("deeper") or maze["root"])


def example_visible_maze() -> dict[str, Any]:
    return {
        "root": "hall",
        "depth": 1,
        "tiles": {
            "hall": {
                "rooms": ["in", "out"],
                "entrance": "in",
                "exit": "out",
                "edges": [{"from": "in", "to": "out", "flip": 0}],
                "shafts": [],
            }
        },
        "start_orientation": 0,
        "goal_orientation": 0,
        "nesting": {},
    }


def _must_clear(tile: Mapping[str, Any]) -> bool:
    return bool(tile.get("shafts"))


def replay_route(maze: Mapping[str, Any], steps: list, max_steps: int = 10_000) -> tuple[bool, str]:
    tiles = maze["tiles"]
    root = maze["root"]
    depth = int(maze["depth"])
    stack: list[tuple[str, int]] = [(root, depth)]
    room = tiles[root]["entrance"]
    orient = int(maze["start_orientation"])
    cleared = False
    used: set[tuple] = set()
    if not isinstance(steps, list) or len(steps) > max_steps:
        return False, "steps missing or too long"
    for i, raw in enumerate(steps):
        if not isinstance(raw, dict) or "op" not in raw:
            return False, f"step {i} malformed"
        tile_name, remaining = stack[-1]
        tile = tiles[tile_name]
        op = raw["op"]
        if op == "move":
            dest = str(raw.get("to", ""))
            found = None
            for edge in tile["edges"]:
                if edge["from"] == room and edge["to"] == dest:
                    found = edge
                    break
            if found is None:
                return False, f"step {i}: no edge {room}->{dest}"
            key = (tuple(stack), room, dest)
            if key in used:
                return False, f"step {i}: reused edge"
            if dest == tile["exit"] and len(stack) == 1 and _must_clear(tile) and not cleared:
                return False, f"step {i}: root exit still sealed"
            used.add(key)
            room = dest
            orient ^= int(found["flip"])
        elif op == "descend":
            if remaining < 1:
                return False, f"step {i}: nesting depth exhausted"
            requested = raw.get("child")
            shaft = None
            for cand in tile.get("shafts") or []:
                cand_child = child_tile(maze, remaining, cand)
                if cand["from"] == room and (requested is None or cand_child == requested or cand["child"] == requested):
                    shaft = cand
                    break
            if shaft is None:
                return False, f"step {i}: no shaft at {room}"
            child = child_tile(maze, remaining, shaft)
            child_rem = remaining - 1 if maze["tiles"][child].get("shafts") else 0
            stack.append((child, child_rem))
            room = tiles[child]["entrance"]
            orient ^= int(shaft["flip"])
        elif op == "ascend":
            if len(stack) == 1 or room != tile["exit"]:
                return False, f"step {i}: illegal ascend"
            child_name, _ = stack.pop()
            parent_name, parent_rem = stack[-1]
            parent = tiles[parent_name]
            matched = next(
                (
                    s
                    for s in (parent.get("shafts") or [])
                    if child_tile(maze, parent_rem, s) == child_name
                ),
                None,
            )
            if matched is None:
                matched = next(
                    (s for s in (parent.get("shafts") or []) if s["child"] == child_name),
                    None,
                )
            if matched is None:
                return False, f"step {i}: no parent shaft"
            room = matched["return"]
            if len(stack) == 1:
                cleared = True
        else:
            return False, f"step {i}: unknown op"
    if len(stack) != 1:
        return False, "ended inside a nested tile"
    if room != tiles[root]["exit"]:
        return False, "not at root exit"
    if orient != int(maze["goal_orientation"]):
        return False, "wrong orientation at exit"
    return True, "ok"


def _neighbours(maze: Mapping[str, Any], state: tuple) -> list[tuple[tuple, dict]]:
    stack, room, orient, cleared, used = state
    tile_name, remaining = stack[-1]
    tile = maze["tiles"][tile_name]
    out: list[tuple[tuple, dict]] = []
    for edge in tile["edges"]:
        if edge["from"] != room:
            continue
        dest = edge["to"]
        key = (stack, room, dest)
        if key in used:
            continue
        if dest == tile["exit"] and len(stack) == 1 and _must_clear(tile) and not cleared:
            continue
        nxt = (
            stack,
            dest,
            orient ^ int(edge["flip"]),
            cleared,
            used | frozenset([key]),
        )
        out.append((nxt, {"op": "move", "to": dest}))
    if remaining >= 1:
        for shaft in tile.get("shafts") or []:
            if shaft["from"] != room:
                continue
            child = child_tile(maze, remaining, shaft)
            child_rem = remaining - 1 if maze["tiles"][child].get("shafts") else 0
            new_stack = stack + ((child, child_rem),)
            nxt = (
                new_stack,
                maze["tiles"][child]["entrance"],
                orient ^ int(shaft["flip"]),
                cleared,
                used,
            )
            out.append((nxt, {"op": "descend", "child": child}))
    if len(stack) > 1 and room == tile["exit"]:
        parent_stack = stack[:-1]
        parent_name, parent_rem = parent_stack[-1]
        child_name = tile_name
        parent = maze["tiles"][parent_name]
        matched = next(
            (
                s
                for s in (parent.get("shafts") or [])
                if child_tile(maze, parent_rem, s) == child_name
            ),
            None,
        )
        if matched is None and parent.get("shafts"):
            matched = parent["shafts"][0]
        if matched is not None:
            new_cleared = cleared or len(parent_stack) == 1
            nxt = (parent_stack, matched["return"], orient, new_cleared, used)
            out.append((nxt, {"op": "ascend"}))
    return out


def shortest_route(maze: Mapping[str, Any], max_nodes: int = 50_000) -> Optional[list[dict[str, Any]]]:
    tiles = maze["tiles"]
    root = maze["root"]
    depth = int(maze["depth"])
    start = (
        ((root, depth),),
        tiles[root]["entrance"],
        int(maze["start_orientation"]),
        False,
        frozenset(),
    )
    goal_room = tiles[root]["exit"]
    goal_orient = int(maze["goal_orientation"])
    queue = deque([start])
    prev: dict[tuple, tuple[Any, dict]] = {}
    seen = {start}
    nodes = 0
    goal_state = None
    while queue:
        state = queue.popleft()
        nodes += 1
        if nodes > max_nodes:
            raise OracleBudgetExceeded(
                f"maze oracle exceeded {max_nodes} states; refusing to call this unsat"
            )
        stack, room, orient, _cleared, _used = state
        if len(stack) == 1 and room == goal_room and orient == goal_orient:
            goal_state = state
            break
        for nxt, action in _neighbours(maze, state):
            if nxt in seen:
                continue
            seen.add(nxt)
            prev[nxt] = (state, action)
            queue.append(nxt)
    if goal_state is None:
        return None
    steps: list[dict[str, Any]] = []
    cur: Any = goal_state
    while cur != start:
        parent, action = prev[cur]
        steps.append(action)
        cur = parent
    steps.reverse()
    return steps


def maze_satisfiable(maze: Mapping[str, Any]) -> bool:
    return shortest_route(maze) is not None


def reference_certificate(maze: Mapping[str, Any]) -> dict[str, Any]:
    steps = shortest_route(maze)
    if steps is None:
        return {"status": "unsat"}
    return {"status": "sat", "steps": steps}


def parse_certificate(raw: Any) -> tuple[Optional[dict[str, Any]], str]:
    if not isinstance(raw, dict):
        return None, "not a dict"
    if raw.get("status") == "unsat":
        return {"status": "unsat"}, ""
    if raw.get("status") != "sat":
        return None, "status"
    if not isinstance(raw.get("steps"), list):
        return None, "sat needs steps"
    return {"status": "sat", "steps": raw["steps"]}, ""


def verify_certificate(maze: Mapping[str, Any], raw: Any) -> tuple[bool, str]:
    cert, err = parse_certificate(raw)
    if cert is None:
        return False, err
    sat = maze_satisfiable(maze)
    if cert["status"] == "unsat":
        return (not sat, "status unsat but a route exists" if sat else "ok")
    if not sat:
        return False, "status sat but no route exists"
    return replay_route(maze, cert["steps"])


def arm_reference(maze: Mapping[str, Any]) -> dict[str, Any]:
    return reference_certificate(maze)


def arm_ignore_orientation(maze: Mapping[str, Any]) -> dict[str, Any]:
    foil = copy.deepcopy(public_maze(maze))
    for tile in foil["tiles"].values():
        for edge in tile["edges"]:
            edge["flip"] = 0
        for shaft in tile.get("shafts") or []:
            shaft["flip"] = 0
    steps = shortest_route(foil)
    if steps is None:
        return {"status": "unsat"}
    return {"status": "sat", "steps": steps}


def evaluate_solver(solve_fn: Callable, maze: dict[str, Any]) -> bool:
    try:
        raw = solve_fn(copy.deepcopy(public_maze(maze)))
    except Exception:
        return False
    ok, _ = verify_certificate(maze, raw)
    return ok


def build_grade_mazes(
    *, depth: int, regime: str, opacity: str, ambiguity: str, seed: int
) -> list[tuple[str, dict[str, Any]]]:
    configured = generate_maze(
        depth=depth, regime=regime, opacity=opacity, ambiguity=ambiguity, seed=seed
    )
    return [
        ("local_visible", example_visible_maze()),
        ("configured", configured),
        (
            "assembled_sat",
            generate_maze(
                depth=max(depth, 1),
                regime=CYCLIC_SAT,
                opacity=opacity,
                ambiguity=CLEAN,
                seed=seed + 11,
            ),
        ),
        (
            "assembled_unsat",
            generate_maze(
                depth=max(depth, 1),
                regime=CYCLIC_UNSAT,
                opacity=opacity,
                ambiguity=CLEAN,
                seed=seed + 13,
            ),
        ),
        ("opaque_twin", relabel_maze(configured, seed + 99)),
        (
            "decoy_heldout",
            generate_maze(
                depth=max(depth, 1),
                regime=regime if regime != TREE else CYCLIC_SAT,
                opacity=opacity,
                ambiguity=DECOY,
                seed=seed + 17,
            ),
        ),
    ]


def grade_solver(
    solve_fn: Callable,
    *,
    depth: int,
    regime: str,
    opacity: str,
    ambiguity: str,
    seed: int,
) -> dict[str, bool]:
    items = build_grade_mazes(
        depth=depth, regime=regime, opacity=opacity, ambiguity=ambiguity, seed=seed
    )
    checks = {name: False for name in CHECK_NAMES}
    named = dict(items)
    for name, maze in items:
        checks[name] = evaluate_solver(solve_fn, maze)
    configured = named["configured"]
    try:
        pub = public_maze(configured)
        first = solve_fn(copy.deepcopy(pub))
        second = solve_fn(copy.deepcopy(pub))
        ok, _ = verify_certificate(configured, first)
        checks["deterministic"] = first == second and ok
    except Exception:
        checks["deterministic"] = False
    return checks
