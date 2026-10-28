#!/usr/bin/env python3
"""Legacy phase-0 baselines and public-input structural rivals for all nine tasks.

Analysis code only. Not imported by any judge. Ground truth is the domain
oracle already in each network.py. Predictions never read `meta`.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import hashlib
import sys
import time
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_net(rel: str, name: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def metrics(truth: list[bool], pred: list[bool]) -> dict[str, Any]:
    n = len(truth)
    agree = sum(int(t == p) for t, p in zip(truth, pred))
    acc = agree / n if n else None
    unsat = [(t, p) for t, p in zip(truth, pred) if not t]
    sat = [(t, p) for t, p in zip(truth, pred) if t]
    unsat_acc = (sum(int(t == p) for t, p in unsat) / len(unsat)) if unsat else None
    sat_acc = (sum(int(t == p) for t, p in sat) / len(sat)) if sat else None
    if sat_acc is None or unsat_acc is None:
        balanced = acc
    else:
        balanced = 0.5 * (sat_acc + unsat_acc)
    # Majority-class constant predictor on this sample (Phase-3 B0 analogue).
    maj = True if sum(truth) >= n / 2 else False
    maj_pred = [maj] * n
    maj_acc = sum(int(t == p) for t, p in zip(truth, maj_pred)) / n if n else None
    return {
        "n": n,
        "n_sat": len(sat),
        "n_unsat": len(unsat),
        "accuracy": acc,
        "agreement": acc,  # same Boolean as the task bit; see audit note
        "unsat_accuracy": unsat_acc,
        "sat_accuracy": sat_acc,
        "balanced_accuracy": balanced,
        "majority_constant": maj,
        "majority_accuracy": maj_acc,
    }


def first_counterexample(rows: list[dict], pred_key: str) -> Any:
    for row in rows:
        if row["truth"] != row[pred_key]:
            keep = {
                k: row[k]
                for k in (
                    "id",
                    "depth",
                    "regime",
                    "opacity",
                    "ambiguity",
                    "order",
                    "seed",
                    "truth",
                    pred_key,
                    "truth_query",
                    "truth_bundle",
                )
                if k in row
            }
            return keep
    return None


# ---------------------------------------------------------------------------
# Maze
# ---------------------------------------------------------------------------

def _tile_walkable(tile: dict) -> bool:
    rooms = set(tile["rooms"])
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in tile["edges"]:
        adj[edge["from"]].append(edge["to"])
    start, goal = tile["entrance"], tile["exit"]
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        for nxt in adj[node]:
            if nxt not in seen and nxt in rooms:
                seen.add(nxt)
                stack.append(nxt)
    return start == goal


def maze_local_sat(maze: dict) -> bool:
    """B0: every tile has an entrance-to-exit walk on its own edges."""
    return all(_tile_walkable(tile) for tile in maze["tiles"].values())


def maze_pairwise_sat(maze: dict) -> bool:
    """B1: local walks plus shaft endpoints land in the parent rooms and child exists."""
    if not maze_local_sat(maze):
        return False
    tiles = maze["tiles"]
    for tile in tiles.values():
        for shaft in tile.get("shafts") or []:
            if shaft["from"] not in tile["rooms"] or shaft["return"] not in tile["rooms"]:
                return False
            child = shaft["child"]
            if child in tiles and not _tile_walkable(tiles[child]):
                return False
    return True


def maze_flatten(maze: dict) -> dict:
    """Permissive child: each shaft becomes a skip edge carrying only the shaft flip.

    Parent corridor flips are kept. Sealing is dropped because the child is
    assumed to return immediately.
    """
    foil = {
        "root": maze["root"],
        "depth": 1,
        "tiles": {},
        "start_orientation": maze["start_orientation"],
        "goal_orientation": maze["goal_orientation"],
        "nesting": {},
    }
    for name, tile in maze["tiles"].items():
        edges = [{"from": e["from"], "to": e["to"], "flip": int(e["flip"])} for e in tile["edges"]]
        for shaft in tile.get("shafts") or []:
            edges.append(
                {"from": shaft["from"], "to": shaft["return"], "flip": int(shaft.get("flip") or 0)}
            )
        foil["tiles"][name] = {
            "rooms": list(tile["rooms"]),
            "entrance": tile["entrance"],
            "exit": tile["exit"],
            "edges": edges,
            "shafts": [],
        }
    return foil


def maze_bounded(maze: dict, k: int) -> dict:
    foil = copy.deepcopy(maze)
    foil["depth"] = min(int(maze["depth"]), k)
    if k <= 0:
        return maze_flatten(maze)
    return foil


def maze_feature_pred(maze: dict) -> bool:
    """Strongest public scalar tried: SAT iff the public flip-sum is 0."""
    total = 0
    for tile in maze["tiles"].values():
        total += sum(int(e.get("flip") or 0) for e in tile["edges"])
        total += sum(int(s.get("flip") or 0) for s in tile.get("shafts") or [])
    return total == 0


def sample_maze(net, n: int = 216) -> list[dict]:
    depths = (1, 2, 3)
    regimes = (net.TREE, net.CYCLIC_SAT, net.CYCLIC_UNSAT)
    opacities = (net.TRANSPARENT, net.OPAQUE)
    ambs = (net.CLEAN, net.DECOY)
    configs = list(product(depths, regimes, opacities, ambs))
    rows = []
    seed = 0
    while len(rows) < n:
        depth, regime, opacity, amb = configs[len(rows) % len(configs)]
        maze = net.generate_maze(
            depth=depth, regime=regime, opacity=opacity, ambiguity=amb, seed=seed
        )
        pub = net.public_maze(maze)
        truth = net.maze_satisfiable(maze)
        flat = maze_flatten(pub)
        rows.append(
            {
                "id": len(rows),
                "depth": depth,
                "regime": regime,
                "opacity": opacity,
                "ambiguity": amb,
                "seed": seed,
                "truth": truth,
                "B0": maze_local_sat(pub),
                "B1": maze_pairwise_sat(pub),
                "Bflat": net.maze_satisfiable(flat),
                "Bk0": net.maze_satisfiable(maze_bounded(pub, 0)),
                "Bk1": net.maze_satisfiable(maze_bounded(pub, 1)),
                "Bk2": net.maze_satisfiable(maze_bounded(pub, 2)),
                "M": maze_feature_pred(pub),
            }
        )
        seed += 1
    return rows


# ---------------------------------------------------------------------------
# Distributed
# ---------------------------------------------------------------------------

def dist_local_sat(job: dict) -> bool:
    """B0: every worker program is nonempty (locally typed)."""
    return all(bool(spec.get("program")) for spec in job["workers"].values())


def dist_pairwise_sat(job: dict) -> bool:
    """B1: programs nonempty and every send/recv names an existing parent/child."""
    if not dist_local_sat(job):
        return False
    workers = job["workers"]
    for spec in workers.values():
        for op in spec["program"]:
            if op.startswith("send:") or op.startswith("recv:"):
                role = op.split(":", 1)[1]
                if role == "parent" and spec["parent"] is None:
                    return False
                if role == "child" and spec["child"] is None:
                    return False
    return True


def dist_flatten(job: dict) -> dict:
    """Permissive child: every non-root worker computes and sends, never locks."""
    foil = copy.deepcopy(job)
    root = job["root"]
    for name, spec in foil["workers"].items():
        if name == root:
            continue
        parent = spec["parent"]
        spec["child"] = None
        spec["program"] = ["compute", "send:parent"] if parent else ["compute"]
    return foil


def dist_bounded(job: dict, k: int) -> dict:
    """Keep only the first k hops from the root; last kept worker becomes a leaf."""
    workers = job["workers"]
    root = job["root"]
    chain = [root]
    cur = root
    while workers[cur]["child"] is not None and len(chain) <= k:
        cur = workers[cur]["child"]
        chain.append(cur)
    kept = set(chain[: k + 1] if k >= 0 else [])
    if k <= 0:
        kept = {root}
    foil = copy.deepcopy(job)
    new_workers = {}
    for name in kept:
        spec = dict(workers[name])
        if spec["child"] not in kept:
            spec["child"] = None
            if "spawn" in spec["program"]:
                spec["program"] = [op for op in spec["program"] if op != "spawn"]
                spec["program"] = [
                    op for op in spec["program"] if not op.endswith(":child")
                ]
                if "compute" not in spec["program"]:
                    spec["program"] = ["compute"] + spec["program"]
        new_workers[name] = spec
    foil["workers"] = new_workers
    return foil


def dist_feature_pred(job: dict) -> bool:
    """SAT unless some public program contains both lock and recv (deadlock shape)."""
    for spec in job["workers"].values():
        prog = spec["program"]
        if "lock" in prog and any(op.startswith("recv:") for op in prog):
            return False
    return True


def sample_dist(net, n: int = 216) -> list[dict]:
    depths = (1, 2, 3)
    regimes = (net.TREE, net.CYCLIC_SAT, net.CYCLIC_UNSAT)
    opacities = (net.TRANSPARENT, net.OPAQUE)
    configs = list(product(depths, regimes, opacities))
    rows = []
    seed = 0
    while len(rows) < n:
        depth, regime, opacity = configs[len(rows) % len(configs)]
        job = net.generate_job(depth=depth, regime=regime, opacity=opacity, seed=seed)
        pub = net.public_job(job)
        truth = net.job_satisfiable(job)
        def safe_sat(j):
            try:
                return net.job_satisfiable(j)
            except net.OracleBudgetExceeded:
                raise  # legacy summary must not turn missing evidence into SAT

        rows.append(
            {
                "id": len(rows),
                "depth": depth,
                "regime": regime,
                "opacity": opacity,
                "seed": seed,
                "truth": truth,
                "B0": dist_local_sat(pub),
                "B1": dist_pairwise_sat(pub),
                "Bflat": safe_sat(dist_flatten(pub)),
                "Bk0": safe_sat(dist_bounded(pub, 0)),
                "Bk1": safe_sat(dist_bounded(pub, 1)),
                "Bk2": safe_sat(dist_bounded(pub, 2)),
                "M": dist_feature_pred(pub),
            }
        )
        seed += 1
    return rows


# ---------------------------------------------------------------------------
# Epistemic
# ---------------------------------------------------------------------------

def _cells(frame: dict, bundle: dict) -> list[set[str]]:
    out = []
    indist = frame["indist"]
    for agent, world in bundle.items():
        blocks = indist[agent]
        cell = None
        for block in blocks:
            as_str = {str(x) for x in block}
            if str(world) in as_str:
                cell = as_str
                break
        out.append(cell if cell is not None else {str(world)})
    return out


def epi_local_sat(model: dict) -> bool:
    """B0: every bundled world exists in the outer frame (local cell nonempty)."""
    bundle = model.get("bundle")
    if not bundle:
        return True
    root = model["levels"][0]
    worlds = {str(w) for w in model["frames"][root]["worlds"]}
    return all(str(w) in worlds for w in bundle.values())


def epi_pairwise_sat(model: dict) -> bool:
    """B1: every pair of outer cells has nonempty intersection."""
    bundle = model.get("bundle")
    if not bundle:
        return True
    if not epi_local_sat(model):
        return False
    root = model["levels"][0]
    cells = _cells(model["frames"][root], bundle)
    for a, b in combinations(range(len(cells)), 2):
        if not (cells[a] & cells[b]):
            return False
    return True


def epi_flatten(model: dict) -> dict:
    """Drop inner frames; evaluate query/bundle on the outermost frame only."""
    outer = model["levels"][0]
    return {
        "agents": model["agents"],
        "frames": {outer: model["frames"][outer]},
        "levels": [outer],
        "actual": [model["actual"][0]],
        "query": model["query"],
        "bundle": model.get("bundle"),
    }


def epi_bounded(model: dict, k: int) -> dict:
    if k <= 0:
        return epi_flatten(model)
    n = min(len(model["levels"]), k)
    levels = model["levels"][:n]
    return {
        "agents": model["agents"],
        "frames": {lev: model["frames"][lev] for lev in levels},
        "levels": levels,
        "actual": list(model["actual"][:n]),
        "query": model["query"],
        "bundle": model.get("bundle"),
    }


def epi_task_sat(net, model: dict) -> bool:
    """Combined task bit used for Phase-0 SAT/UNSAT counts.

    Query must hold at `actual`. If a bundle is present it must be possible.
    TREE instances have no bundle, so the bit is exactly query_value.
    """
    if not net.query_value(model):
        return False
    possible = net.bundle_possible(model)
    if possible is None:
        return True
    return bool(possible)


def epi_feature_pred(model: dict) -> bool:
    """SAT iff there is no bundle, or the two reported worlds are equal."""
    bundle = model.get("bundle")
    if not bundle:
        return True
    vals = list(bundle.values())
    return len(set(vals)) <= 1


def sample_epi(net, n: int = 216) -> list[dict]:
    depths = (1, 2, 3)
    regimes = (net.TREE, net.CYCLIC_SAT, net.CYCLIC_UNSAT)
    opacities = (net.TRANSPARENT, net.OPAQUE)
    orders = (0, 1, 2)
    configs = list(product(depths, regimes, opacities, orders))
    rows = []
    seed = 0
    while len(rows) < n:
        depth, regime, opacity, order = configs[len(rows) % len(configs)]
        model = net.generate_model(
            depth=depth, regime=regime, opacity=opacity, order=order, seed=seed
        )
        pub = net.public_model(model)
        truth = epi_task_sat(net, model)
        bundle = net.bundle_possible(model)
        flat = epi_flatten(pub)
        rows.append(
            {
                "id": len(rows),
                "depth": depth,
                "regime": regime,
                "opacity": opacity,
                "order": order,
                "seed": seed,
                "truth": truth,
                "has_bundle": bundle is not None,
                "truth_query": net.query_value(model),
                "truth_bundle": bundle,
                "B0": epi_local_sat(pub) and True,  # local bundle; query ignored
                "B1": epi_pairwise_sat(pub),
                "Bflat": epi_task_sat(net, flat),
                "Bk0": epi_task_sat(net, epi_bounded(pub, 0)),
                "Bk1": epi_task_sat(net, epi_bounded(pub, 1)),
                "Bk2": epi_task_sat(net, epi_bounded(pub, 2)),
                "M": epi_feature_pred(pub),
            }
        )
        seed += 1
    return rows


def summarize(name: str, rows: list[dict], keys: tuple[str, ...]) -> dict[str, Any]:
    truth = [r["truth"] for r in rows]
    out: dict[str, Any] = {
        "environment": name,
        "sample": len(rows),
        "sat": sum(1 for t in truth if t),
        "unsat": sum(1 for t in truth if not t),
    }
    for key in keys:
        pred = [r[key] for r in rows]
        out[key] = metrics(truth, pred)
        out[f"{key}_counterexample"] = first_counterexample(rows, key)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=216)
    parser.add_argument("--json", default="")
    parser.add_argument("--structural", action="store_true", help="record public-input rivals across all nine environments")
    parser.add_argument("--depth", default="2")
    parser.add_argument("--seed", default="41")
    args = parser.parse_args(argv)
    if args.structural:
        return StructuralRivals().main(args)
    maze = load_net("envs/cat_theo/recursive_maze_gluing/files/network.py", "maze_net")
    dist = load_net("envs/cat_theo/recursive_distributed_gluing/files/network.py", "dist_net")
    epi = load_net("envs/cat_theo/recursive_epistemic_gluing/files/network.py", "epi_net")
    maze_rows = sample_maze(maze, args.n)
    dist_rows = sample_dist(dist, args.n)
    epi_rows = sample_epi(epi, args.n)
    epi_bundle = [r for r in epi_rows if r["has_bundle"]]
    keys = ("B0", "B1", "Bflat", "Bk0", "Bk1", "Bk2", "M")
    report = {
        "n_requested": args.n,
        "maze": summarize("recursive_maze_gluing", maze_rows, keys),
        "distributed": summarize("recursive_distributed_gluing", dist_rows, keys),
        "epistemic_task": summarize("recursive_epistemic_gluing", epi_rows, keys),
        "epistemic_bundle_only": summarize(
            "recursive_epistemic_gluing_bundle", epi_bundle, keys
        ),
    }
    text = json.dumps(report, indent=2, default=str)
    if args.json:
        path = Path(args.json)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


class StructuralRivals:
    """Provider-free certificate rivals using the existing grading instances.

    Independence is declared per strategy. Reference-conditioned negative
    controls are never labelled independent solvers. No elapsed-time or
    accuracy claim exists until this runner is executed.
    """

    environments = (
        "recursive_gluing", "recursive_gluing_discovery", "recursive_maze_gluing",
        "recursive_distributed_gluing", "recursive_epistemic_gluing",
        "recursive_compiler_bootstrap", "recursive_error_correcting_codes",
        "recursive_coarse_graining", "recursive_holonomy_gluing",
    )

    def gluing_local(self, instance):
        return {"status": "sat", "assignment": self.net.naive_spanning_forest_assignment(instance)}

    def epistemic_facts(self, instance):
        cert = self.net.reference_certificate(instance)
        cert["query_value"] = self.net.atom_at(instance, "p", tuple(instance["actual"]))
        return cert

    def configure(self, environment, depth, seed):
        net = load_net("envs/cat_theo/" + environment + "/files/network.py", "rival_" + environment)
        self.net = net
        if environment == "recursive_gluing":
            items = net.build_grade_instances(depth=depth, domain_size=3, regime=net.CYCLIC_SAT, label_mode=net.OPAQUE, seed=seed)
            return net, None, items, (("expanded_csp", "reference", net.reference_solve),
                                     ("spanning_forest", "local_constraint_ablation", self.gluing_local))
        if environment == "recursive_gluing_discovery":
            items = net.build_grade_grammars(depth=depth, interface_size=3, regime=net.CYCLIC_SAT, opacity=net.OPAQUE, ambiguity=net.CLEAN, seed=seed)
            return net, net.public_grammar, items, (("compact_relations", "reference", net.reference_certificate),
                ("expanded_csp", "independent_answer_construction", net.arm_expanded),
                ("copy_leaf", "local_template", net.arm_copy_leaf_upward))
        if environment == "recursive_maze_gluing":
            items = net.build_grade_mazes(depth=depth, regime=net.CYCLIC_SAT, opacity=net.OPAQUE, ambiguity=net.CLEAN, seed=seed)
            return net, net.public_maze, items, (("full_state_bfs", "reference_search", net.reference_certificate),
                ("ignore_orientation", "search_with_ablation", net.arm_ignore_orientation))
        if environment == "recursive_distributed_gluing":
            items = net.build_grade_jobs(depth=depth, regime=net.TREE, opacity=net.OPAQUE, seed=seed)
            return net, net.public_job, items, (("scheduler_bfs", "reference_search", net.reference_certificate),
                ("ignore_capacity", "search_with_ablation", net.SchedulerControls().capacity_blind))
        if environment == "recursive_epistemic_gluing":
            items = net.build_grade_models(depth=depth, regime=net.CYCLIC_SAT, opacity=net.OPAQUE, order=3, seed=seed)
            return net, net.public_model, items, (("finite_modal_evaluation", "reference_enumeration", net.reference_certificate),
                ("actual_facts", "reference_conditioned_negative_control", self.epistemic_facts))
        if environment == "recursive_compiler_bootstrap":
            items = net.build_grade_items(depth=depth, regime=net.RECURSIVE, representation=net.REVEALED, seed=seed)
            return net, net.public_instance, items, (("known_l1_compiler", "reference_program", net.reference_certificate),
                ("local_decoder", "reference_conditioned_negative_control", net.arm_local_only))
        if environment == "recursive_error_correcting_codes":
            items = net.build_grade_items(depth=depth, regime=net.RECURSIVE, representation=net.INFERRED, seed=seed)
            return net, net.public_instance, items, (("field_elimination", "reference", net.reference_certificate),
                ("exhaustive_coordinates", "independent_search_shared_assignment_predicate", net.enumeration_certificate))
        if environment == "recursive_coarse_graining":
            items = net.build_grade_items(depth=depth, regime=net.RECURSIVE, representation=net.INFERRED, seed=seed)
            return net, net.public_instance, items, (("matrix_and_partition_enumeration", "reference_direct_algorithm", net.reference_certificate),
                ("local_table", "nuisance_certified_ablation", net.arm_local_only))
        if environment == "recursive_holonomy_gluing":
            items = net.build_grade_items(depth=depth, family=net.AFF, regime=net.REC_COMP, representation=net.INFERRED, seed=seed)
            return net, net.public_instance, items, (("algebraic_composition", "reference", net.reference_certificate),
                ("finite_state_transport", "direct_algorithm_shared_map_semantics", net.arm_revealed_compose))
        raise ValueError("unknown recursive environment")

    def record(self, environment, net, instance, public, strategy):
        name, independence, solve = strategy
        record = {"strategy": name, "independence": independence,
                  "input_sha256": hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest(),
                  "certificate_valid": None, "outcome": "unmeasured"}
        started = time.perf_counter()
        try:
            candidate = solve(copy.deepcopy(public))
        except net.OracleBudgetExceeded:
            record["outcome"] = "solver_budget_exhausted"
            record["solver_seconds"] = time.perf_counter() - started
            return record
        except Exception as exc:
            record["outcome"] = "solver_error"
            record["error"] = str(exc)
            return record
        record["solver_seconds"] = time.perf_counter() - started
        try:
            if environment == "recursive_gluing":
                parsed, reason = net.parse_solve_output(instance, candidate)
                valid = parsed is not None
                if valid and parsed["status"] == "unsat":
                    valid = not net.oracle_satisfiable(instance)
                    reason = "checked global unsatisfiability"
            else:
                valid, reason = net.verify_certificate(instance, candidate)
        except net.OracleBudgetExceeded:
            record["outcome"] = "oracle_budget_exhausted"
            return record
        except Exception as exc:
            record["outcome"] = "verification_error"
            record["error"] = str(exc)
            return record
        record["certificate_valid"] = int(valid)
        record["outcome"] = "accepted" if valid else "rejected"
        record["reason"] = reason
        return record

    def strategies(self, environment, net, instance, public, strategies):
        if not strategies:
            return ()
        return (self.record(environment, net, instance, public, strategies[0]),) + self.strategies(
            environment, net, instance, public, strategies[1:])

    def items(self, environment, net, public_fn, items, strategies):
        if not items:
            return ()
        name, instance = items[0]
        public = public_fn(instance) if public_fn is not None else copy.deepcopy(instance)
        row = {"check": name, "rivals": self.strategies(environment, net, instance, public, strategies)}
        return (row,) + self.items(environment, net, public_fn, items[1:], strategies)

    def family(self, environments, depth, seed):
        if not environments:
            return ()
        environment = environments[0]
        net, public_fn, items, strategies = self.configure(environment, depth, seed)
        row = {"environment": environment, "requested_depth": depth, "seed": seed,
               "network_sha256": hashlib.sha256((ROOT / "envs" / "cat_theo" / environment / "files" / "network.py").read_bytes()).hexdigest(),
               "checks": self.items(environment, net, public_fn, tuple(items), strategies)}
        return (row,) + self.family(environments[1:], depth, seed)

    def main(self, args):
        report = {"schema_version": 1, "provider_calls": 0,
                  "scope": "algorithm controls, no model capability claims",
                  "resource_policy": "budget exhaustion has no certificate score and is never SAT or UNSAT",
                  "declared_limits": {
                      "gluing_csp_nodes": 200000, "discovery_expansion_depth": 4,
                      "discovery_csp_nodes_per_projection": 200000,
                      "maze_search_states": 50000, "scheduler_search_states": 80000,
                      "epistemic_uncached_formula_states": 50000,
                      "l1_steps_per_vm_invocation": 200000,
                      "code_exhaustive_candidates": 80000, "quotient_microstates": 12,
                  },
                  "environments": self.family(self.environments, int(args.depth), int(args.seed))}
        text = json.dumps(report, indent=2)
        if args.json:
            path = Path(args.json)
            if not path.is_absolute():
                path = ROOT / path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        else:
            sys.stdout.write(text + "\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
