#!/usr/bin/env python3
"""Measure compact vs expanded recursive-gluing representations.

Compares the production compact grammar/oracle with explicit unfolding and the
expanded CSP solver on matched instances. Does not call models, mutate campaign
state, or treat resource limits as unsatisfiability.

Usage:
    python tools/recursive_gluing_scaling.py
    python tools/recursive_gluing_scaling.py --json docs/decisions/2026-10-16-recursive-gluing-scaling.json
    python tools/recursive_gluing_scaling.py --compact-depths 3,6 --expand-depths 3 --repeats 1 --json -
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[1]
NET_PATH = ROOT / "envs" / "cat_theo" / "recursive_gluing_discovery" / "files" / "network.py"
DEFAULT_COMPACT = (3, 6, 12, 24, 48, 96)
DEFAULT_EXPAND = (3, 6, 9, 12)


def load_network():
    spec = importlib.util.spec_from_file_location("rgd_scaling_network", NET_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {NET_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def peak_rss_kb() -> Optional[int]:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        return None
    if sys.platform == "darwin":
        return int(round(usage / 1024.0))
    return int(usage)


def apply_memory_limit_mb(limit_mb: int) -> Optional[str]:
    if limit_mb <= 0:
        return None
    try:
        import resource

        cap = int(limit_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        return None
    except (ImportError, OSError, ValueError) as exc:
        return f"rlimit_as_unavailable:{type(exc).__name__}"


def _parse_depths(text: str) -> list[int]:
    depths = [int(part.strip()) for part in text.split(",") if part.strip()]
    if not depths or any(d < 1 for d in depths):
        raise argparse.ArgumentTypeError("depths must be positive integers")
    return depths


def _parse_depths_optional(text: str) -> list[int]:
    if text.strip().lower() in ("", "none", "-"):
        return []
    return _parse_depths(text)


def median_ms(samples: list[float]) -> Optional[float]:
    if not samples:
        return None
    return round(statistics.median(samples), 3)


def grammar_kwargs(args: argparse.Namespace, depth: int) -> dict[str, Any]:
    return dict(
        depth=depth,
        interface_size=args.interface_size,
        regime=args.regime,
        opacity=args.opacity,
        ambiguity=args.ambiguity,
        seed=args.seed,
    )


def worker_compact(args: argparse.Namespace) -> dict[str, Any]:
    net = load_network()
    t_gen = time.perf_counter()
    grammar = net.generate_grammar(**grammar_kwargs(args, args.depth))
    gen_ms = (time.perf_counter() - t_gen) * 1000.0
    t_or = time.perf_counter()
    cert = net.reference_certificate(grammar)
    oracle_ms = (time.perf_counter() - t_or) * 1000.0
    t_ver = time.perf_counter()
    ok, reason = net.verify_certificate(grammar, cert)
    verify_ms = (time.perf_counter() - t_ver) * 1000.0
    if not ok:
        raise RuntimeError(f"compact certificate failed verification: {reason}")
    realizable = cert["realizable"]
    return {
        "kind": "measured",
        "stage": "compact",
        "depth": args.depth,
        "occurrences": net.unfolded_occurrences(args.depth),
        "leaves": net.unfolded_leaves(args.depth),
        "grammar_bytes": net.compact_input_bytes(grammar),
        "cert_bytes": net.certificate_bytes(cert),
        "summary_cells": net.summary_cells(realizable),
        "summary_depth_keys": net.summary_depth_keys(realizable),
        "status": cert["status"],
        "gen_ms": round(gen_ms, 3),
        "oracle_ms": round(oracle_ms, 3),
        "verify_ms": round(verify_ms, 3),
        "peak_rss_kb": peak_rss_kb(),
        "expanded": False,
    }


def worker_expand(args: argparse.Namespace) -> dict[str, Any]:
    limit_note = apply_memory_limit_mb(args.memory_mb)
    net = load_network()
    t_gen = time.perf_counter()
    grammar = net.generate_grammar(**grammar_kwargs(args, args.depth))
    gen_ms = (time.perf_counter() - t_gen) * 1000.0
    t_ex = time.perf_counter()
    instance = net.expand_grammar(grammar, max_depth=args.depth)
    expand_ms = (time.perf_counter() - t_ex) * 1000.0
    occ = net.expanded_occurrence_count(instance)
    variables = len(instance["regions"])
    overlaps = len(instance["overlaps"])
    ser_bytes = None
    serialize_ms = None
    if args.serialize:
        t_ser = time.perf_counter()
        ser_bytes = len(json.dumps(instance, separators=(",", ":")))
        serialize_ms = (time.perf_counter() - t_ser) * 1000.0
    sat = None
    solve_ms = None
    if args.solve:
        t_sol = time.perf_counter()
        solution = net._csp_solution(instance)
        solve_ms = (time.perf_counter() - t_sol) * 1000.0
        sat = solution is not None
    return {
        "kind": "measured",
        "stage": "expand",
        "depth": args.depth,
        "occurrences": occ,
        "analytic_occurrences": net.unfolded_occurrences(args.depth),
        "variables": variables,
        "analytic_variables": net.expanded_port_variables(args.depth),
        "overlaps": overlaps,
        "analytic_overlaps": net.expanded_overlap_count(
            args.depth, closing=net.grammar_has_closing(grammar)
        ),
        "serialized_bytes": ser_bytes,
        "sat": sat,
        "gen_ms": round(gen_ms, 3),
        "expand_ms": round(expand_ms, 3),
        "serialize_ms": None if serialize_ms is None else round(serialize_ms, 3),
        "solve_ms": None if solve_ms is None else round(solve_ms, 3),
        "peak_rss_kb": peak_rss_kb(),
        "memory_limit_note": limit_note,
        "used_compact_oracle": False,
    }


def run_worker_process(
    worker: str,
    args: argparse.Namespace,
    depth: int,
    *,
    memory_mb: int,
    timeout_s: float,
    solve: bool,
    serialize: bool,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        worker,
        "--depth",
        str(depth),
        "--interface-size",
        str(args.interface_size),
        "--regime",
        args.regime,
        "--opacity",
        args.opacity,
        "--ambiguity",
        args.ambiguity,
        "--seed",
        str(args.seed),
        "--memory-mb",
        str(memory_mb),
    ]
    if solve:
        cmd.append("--solve")
    if serialize:
        cmd.append("--serialize")
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return {
            "kind": "resource_limit",
            "stage": worker,
            "depth": depth,
            "reason": f"timeout after {timeout_s}s",
            "timeout_s": timeout_s,
            "memory_mb": memory_mb,
        }
    if proc.returncode != 0:
        stderr = (proc.stderr or "")[-800:]
        reason = "nonzero_exit"
        if "MemoryError" in (proc.stderr or "") or proc.returncode in (-9, 137):
            reason = "memory_limit"
        return {
            "kind": "resource_limit",
            "stage": worker,
            "depth": depth,
            "reason": reason,
            "returncode": proc.returncode,
            "stderr_tail": stderr,
            "timeout_s": timeout_s,
            "memory_mb": memory_mb,
        }
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "kind": "resource_limit",
            "stage": worker,
            "depth": depth,
            "reason": "unparseable_worker_stdout",
            "stdout_tail": (proc.stdout or "")[-400:],
            "stderr_tail": (proc.stderr or "")[-400:],
        }


def aggregate_compact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    out = {
        "kind": "measured",
        "depth": first["depth"],
        "occurrences": first["occurrences"],
        "leaves": first["leaves"],
        "grammar_bytes": first["grammar_bytes"],
        "cert_bytes": first["cert_bytes"],
        "summary_cells": first["summary_cells"],
        "summary_depth_keys": first["summary_depth_keys"],
        "status": first["status"],
        "repeats": len(rows),
        "gen_ms_median": median_ms([row["gen_ms"] for row in rows]),
        "oracle_ms_median": median_ms([row["oracle_ms"] for row in rows]),
        "verify_ms_median": median_ms([row["verify_ms"] for row in rows]),
        "peak_rss_kb_max": max(
            (row["peak_rss_kb"] for row in rows if row.get("peak_rss_kb") is not None),
            default=None,
        ),
        "expanded": False,
    }
    return out


def aggregate_expand(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if any(row.get("kind") != "measured" for row in rows):
        return rows[0]
    first = rows[0]
    return {
        "kind": "measured",
        "depth": first["depth"],
        "occurrences": first["occurrences"],
        "analytic_occurrences": first["analytic_occurrences"],
        "variables": first["variables"],
        "analytic_variables": first["analytic_variables"],
        "overlaps": first["overlaps"],
        "analytic_overlaps": first["analytic_overlaps"],
        "serialized_bytes": first["serialized_bytes"],
        "sat": first["sat"],
        "repeats": len(rows),
        "gen_ms_median": median_ms([row["gen_ms"] for row in rows]),
        "expand_ms_median": median_ms([row["expand_ms"] for row in rows]),
        "serialize_ms_median": median_ms(
            [row["serialize_ms"] for row in rows if row.get("serialize_ms") is not None]
        ),
        "solve_ms_median": median_ms(
            [row["solve_ms"] for row in rows if row.get("solve_ms") is not None]
        ),
        "peak_rss_kb_max": max(
            (row["peak_rss_kb"] for row in rows if row.get("peak_rss_kb") is not None),
            default=None,
        ),
        "used_compact_oracle": False,
        "memory_limit_note": first.get("memory_limit_note"),
    }


def analytic_expanded_row(net, depth: int, closing: bool, reason: str) -> dict[str, Any]:
    return {
        "kind": "analytic_only",
        "depth": depth,
        "reason": reason,
        "analytic_occurrences": net.unfolded_occurrences(depth),
        "analytic_variables": net.expanded_port_variables(depth),
        "analytic_overlaps": net.expanded_overlap_count(depth, closing=closing),
        "measured": False,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    net = load_network()
    closing = args.regime != "tree"
    compact_rows = []
    for depth in args.compact_depths:
        samples = [
            run_worker_process(
                "compact",
                args,
                depth,
                memory_mb=0,
                timeout_s=args.compact_timeout_s,
                solve=False,
                serialize=False,
            )
            for _ in range(args.repeats)
        ]
        if all(row.get("kind") == "measured" for row in samples):
            compact_rows.append(aggregate_compact(samples))
        else:
            compact_rows.append(samples[0])

    expanded_rows: list[dict[str, Any]] = []
    measured_expand = set(args.expand_depths)
    attempt = set(args.attempt_expand)

    for depth in sorted(measured_expand | attempt | set(args.compact_depths)):
        if depth in measured_expand or depth in attempt:
            memory_mb = args.attempt_memory_mb if depth in attempt and depth not in measured_expand else args.expand_memory_mb
            timeout_s = args.attempt_timeout_s if depth in attempt and depth not in measured_expand else args.expand_timeout_s
            samples = [
                run_worker_process(
                    "expand",
                    args,
                    depth,
                    memory_mb=memory_mb,
                    timeout_s=timeout_s,
                    solve=True,
                    serialize=True,
                )
                for _ in range(args.repeats)
            ]
            expanded_rows.append(aggregate_expand(samples))
        elif depth >= 15:
            expanded_rows.append(
                analytic_expanded_row(
                    net,
                    depth,
                    closing,
                    "not materialized; occurrence count is exact, cost is unmeasured",
                )
            )

    config = {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
        "seed": args.seed,
        "interface_size": args.interface_size,
        "regime": args.regime,
        "opacity": args.opacity,
        "ambiguity": args.ambiguity,
        "repeats": args.repeats,
        "compact_depths": list(args.compact_depths),
        "expand_depths": list(args.expand_depths),
        "attempt_expand": list(args.attempt_expand),
        "expand_memory_mb": args.expand_memory_mb,
        "expand_timeout_s": args.expand_timeout_s,
        "attempt_memory_mb": args.attempt_memory_mb,
        "attempt_timeout_s": args.attempt_timeout_s,
        "compact_timeout_s": args.compact_timeout_s,
        "rss_units": "kilobytes via resource.ru_maxrss (Linux KB; Darwin bytes converted to KB)",
        "timing": "time.perf_counter wall time; medians over repeats; stages separated",
        "network_module": str(NET_PATH.relative_to(ROOT)),
        "expanded_solver": "network._csp_solution on expand_grammar output; does not call compact_summaries",
        "campaign_state": "untouched",
    }
    formulas = {
        "occurrences": "2**(depth+1) - 1",
        "leaves": "2**depth",
        "port_variables": "2 * occurrences",
        "overlaps": "2**(depth+2) - 3 + (1 if closing else 0)",
        "certificate_cells_clean_translation": "interface_size * (depth + 1)  # tip@0 + stem@1..depth",
    }
    return {
        "config": config,
        "formulas": formulas,
        "compact": compact_rows,
        "expanded": expanded_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=["compact", "expand"], default="")
    parser.add_argument("--depth", type=int, default=0)
    parser.add_argument("--compact-depths", type=_parse_depths, default=list(DEFAULT_COMPACT))
    parser.add_argument("--expand-depths", type=_parse_depths, default=list(DEFAULT_EXPAND))
    parser.add_argument(
        "--attempt-expand",
        type=_parse_depths_optional,
        default=[15],
        help="Extra depths tried only in an isolated subprocess. Pass 'none' to skip.",
    )
    parser.add_argument("--interface-size", type=int, default=5)
    parser.add_argument("--regime", default="cyclic_unsat")
    parser.add_argument("--opacity", default="opaque")
    parser.add_argument("--ambiguity", default="clean")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--expand-memory-mb", type=int, default=1024)
    parser.add_argument("--expand-timeout-s", type=float, default=45)
    parser.add_argument("--attempt-memory-mb", type=int, default=1536)
    parser.add_argument("--attempt-timeout-s", type=float, default=90)
    parser.add_argument("--compact-timeout-s", type=float, default=30)
    parser.add_argument("--memory-mb", type=int, default=0, help="worker-only AS cap")
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--serialize", action="store_true")
    parser.add_argument("--json", default="", help="output path, or - for stdout")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.worker:
        if args.depth < 1:
            print("worker requires --depth", file=sys.stderr)
            return 2
        payload = worker_compact(args) if args.worker == "compact" else worker_expand(args)
        json.dump(payload, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    report = build_report(args)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.json == "-" or args.json == "":
        sys.stdout.write(text + "\n")
    else:
        path = Path(args.json)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
