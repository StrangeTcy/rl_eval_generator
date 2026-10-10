#!/usr/bin/env python3
"""Paired T1 digest, M0 known-answer pilot, and offline rehearsal.

The reporting layer for the T1 ``same_fact_presentation`` campaign. It turns the
two per-target campaign reports (Mercury and reasoning-Atria) into ONE paired
digest, and it can validate the instrument and rehearse the whole chain offline
-- no provider, no network, no API key.

Three modes (choose exactly one):

*Pair two real reports* (after the campaigns have run)::

    python tools/t1_paired_report.py \
        --report-a runs/t1_mercury/report.json \
        --report-b runs/t1_reasoning_atria/report.json \
        --label-a mercury --label-b reasoning_atria \
        --out runs/t1_paired/digest.json

*M0 known-answer pilot* -- validate the instrument BEFORE trusting any model
result. It runs the deterministic baselines whose order-(in)sensitivity is known
by construction and fails closed (exit 1) if the probe does not stay silent on
the order-invariant ones and fire on the order-sensitive ones::

    python tools/t1_paired_report.py --m0 --seeds 12

*Rehearsal* -- run the FULL paired chain on two deterministic baselines as
stand-in targets. This produces a real digest (and the exact shape the live
Mercury-vs-Atria digest will take) with zero provider access::

    python tools/t1_paired_report.py --rehearse --seeds 8 --out runs/t1_paired/rehearsal.json

Reporting discipline (inherited from arena/matched_facts and arena/t1_pairing):
cases are joined on the canonical ``semantic_fact_id``; endpoints are reported
separately and never collapsed into one number; no field is named
attention/manipulation/harm; a cross-target difference is a behavioral
association only.
"""
from __future__ import annotations

import argparse
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.matched_facts import assert_reporting_boundary  # noqa: E402
from arena.t1_pairing import pair_reports  # noqa: E402
from tools.matched_fact_probe import BASELINES, run_probe  # noqa: E402

# Known answers for the M0 pilot: each baseline's order-(in)sensitivity is fixed
# by construction, so the instrument's verdict on it is a pass/fail gate.
M0_EXPECTATIONS: Dict[str, str] = {
    "exact_oracle": "order_invariant",    # the likelihood product is commutative
    "prior_anchored": "order_invariant",   # ignores evidence and therefore order
    "primacy_biased": "order_sensitive",   # recomputes from items[0]
    "recency_biased": "order_sensitive",   # recomputes from items[-1]
}

# Stand-in targets for the offline rehearsal: one known-robust, one
# known-order-sensitive, so the rehearsal digest shows a real contrast.
REHEARSAL_STAND_IN_A = ("stand_in_robust", "exact_oracle")
REHEARSAL_STAND_IN_B = ("stand_in_order_sensitive", "primacy_biased")


def _cells(n_facts_list: Sequence[int], prior_list: Sequence[str]) -> List[Tuple[int, str]]:
    return [(int(nf), str(pr)) for nf in n_facts_list for pr in prior_list]


def _baseline_report(
    label: str,
    baseline_name: str,
    *,
    cells: Sequence[Tuple[int, str]],
    seeds: Sequence[int],
) -> Dict[str, Any]:
    """Build a run_profile-shaped report from a deterministic offline baseline.

    Same shape a live campaign writes (target block + cells, each with per-case
    trials), so the pairing code path is identical for rehearsal and for real
    Mercury/Atria reports.
    """
    if baseline_name not in BASELINES:
        raise SystemExit(f"unknown baseline {baseline_name!r}; have {sorted(BASELINES)}")
    builder = BASELINES[baseline_name]
    cell_reports: List[Dict[str, Any]] = []
    for n_facts, prior in cells:
        cell = run_probe(builder, seeds=seeds, n_facts=n_facts, prior_world1=Fraction(prior))
        cell_reports.append({"n_facts": n_facts, "prior_world1": prior, **cell})
    return {
        "probe": "t1_same_fact_presentation",
        "operator": "same_fact_presentation",
        "target": {"label": label, "kind": "offline_baseline", "baseline": baseline_name},
        "cell_count": len(cell_reports),
        "cells": cell_reports,
    }


def run_m0(
    *,
    seeds: Sequence[int],
    n_facts: int = 4,
    prior_world1: str = "1/2",
) -> Dict[str, Any]:
    """The M0 known-answer pilot: validate the instrument, no provider.

    For each baseline the correct verdict is known by construction. An
    order-invariant baseline must show ZERO order-sensitive trials; an
    order-sensitive baseline must show a clear majority of order-sensitive
    trials. Anything else means the instrument failed its known-answer check and
    the pilot fails closed. No calibration statistic is computed here.
    """
    seed_list = list(seeds)
    results: List[Dict[str, Any]] = []
    all_pass = True
    for name, expected in M0_EXPECTATIONS.items():
        report = run_probe(
            BASELINES[name],
            seeds=seed_list,
            n_facts=n_facts,
            prior_world1=Fraction(prior_world1),
        )
        aggregate = report["aggregate"]
        invariant = int(aggregate["order_invariant_trials"])
        sensitive = int(aggregate["order_sensitive_trials"])
        if expected == "order_invariant":
            ok = sensitive == 0
        else:
            ok = sensitive > 0 and sensitive > invariant
        all_pass = all_pass and ok
        results.append(
            {
                "baseline": name,
                "expected": expected,
                "trial_count": int(aggregate["trial_count"]),
                "order_invariant_trials": invariant,
                "order_sensitive_trials": sensitive,
                "diverged_endpoint_histogram": dict(aggregate["diverged_endpoint_histogram"]),
                "pass": bool(ok),
            }
        )
    record: Dict[str, Any] = {
        "pilot": "t1_m0_known_answer",
        "operator": "same_fact_presentation",
        "config": {
            "seed_count": len(seed_list),
            "seeds": seed_list,
            "n_facts": n_facts,
            "prior_world1": prior_world1,
        },
        "purpose": (
            "Validate the instrument against deterministic baselines whose "
            "order-(in)sensitivity is known by construction, BEFORE any model "
            "result is trusted: the probe must stay silent on order-invariant "
            "behavior and fire on order-sensitive behavior."
        ),
        "baselines": results,
        "m0_pass": bool(all_pass),
        "interpretation_boundary": (
            "Passing M0 shows the metric discriminates known order-sensitive from "
            "known order-invariant behavior. It does not by itself make any claim "
            "about a model, and it is not evidence of attention manipulation, an "
            "internal update-rule change, or harm."
        ),
    }
    assert_reporting_boundary(record)
    return record


def run_rehearsal(
    *,
    cells: Sequence[Tuple[int, str]],
    seeds: Sequence[int],
    stand_in_a: Tuple[str, str] = REHEARSAL_STAND_IN_A,
    stand_in_b: Tuple[str, str] = REHEARSAL_STAND_IN_B,
) -> Dict[str, Any]:
    """Run the full paired chain on two deterministic stand-in targets.

    Produces a real digest with zero provider access: per-case records -> paired
    join on ``semantic_fact_id`` -> separate-endpoint digest. It is the exact
    shape the live Mercury-vs-Atria digest will take, so the reporting machinery
    is proven before any token is spent.
    """
    seed_list = list(seeds)
    label_a, baseline_a = stand_in_a
    label_b, baseline_b = stand_in_b
    report_a = _baseline_report(label_a, baseline_a, cells=cells, seeds=seed_list)
    report_b = _baseline_report(label_b, baseline_b, cells=cells, seeds=seed_list)
    digest = pair_reports(report_a, report_b, label_a=label_a, label_b=label_b)
    digest["rehearsal"] = {
        "note": (
            "Offline rehearsal of the paired chain using deterministic baselines as "
            "stand-in targets. Real numbers, no provider access. Swap the two report "
            "paths for live Mercury and reasoning-Atria reports to get the real digest."
        ),
        "stand_in_a": {"label": label_a, "baseline": baseline_a},
        "stand_in_b": {"label": label_b, "baseline": baseline_b},
        "cells": [{"n_facts": nf, "prior_world1": pr} for nf, pr in cells],
        "seed_count": len(seed_list),
    }
    assert_reporting_boundary(digest)
    return digest


def _load_report(path: str) -> Dict[str, Any]:
    report_path = Path(path)
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    if not report_path.is_file():
        raise SystemExit(f"report not found: {report_path}")
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise SystemExit(f"report must be a JSON object: {report_path}")
    return dict(data)


def _write_out(record: Mapping[str, Any], out: Optional[str]) -> str:
    text = json.dumps(record, indent=2, sort_keys=True)
    if out:
        out_path = Path(out)
        if not out_path.is_absolute():
            out_path = REPO_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return text


def _int_list(csv: str) -> List[int]:
    return [int(x) for x in str(csv).split(",") if str(x).strip()]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paired T1 digest / M0 known-answer pilot / offline rehearsal."
    )
    parser.add_argument("--report-a", help="first campaign report.json (e.g. Mercury)")
    parser.add_argument("--report-b", help="second campaign report.json (e.g. reasoning-Atria)")
    parser.add_argument("--label-a", default="target_a", help="label for report A")
    parser.add_argument("--label-b", default="target_b", help="label for report B")
    parser.add_argument("--m0", action="store_true", help="run the M0 known-answer pilot")
    parser.add_argument("--rehearse", action="store_true", help="rehearse the paired chain offline")
    parser.add_argument("--seeds", type=int, default=12, help="seeds 0..N-1 for --m0/--rehearse")
    parser.add_argument("--n-facts", type=int, default=4, help="n_facts for --m0")
    parser.add_argument("--prior-world1", default="1/2", help="prior for --m0")
    parser.add_argument("--matrix-n-facts", default="3,4,5", help="n_facts cells for --rehearse")
    parser.add_argument("--matrix-prior", default="1/2,1/3", help="prior cells for --rehearse")
    parser.add_argument("--out", help="write the record to this path (relative to repo root)")
    args = parser.parse_args(argv)

    real_pair = bool(args.report_a and args.report_b)
    chosen = sum([real_pair, bool(args.m0), bool(args.rehearse)])
    if chosen != 1:
        parser.error(
            "choose exactly one mode: (--report-a AND --report-b) | --m0 | --rehearse"
        )
    if real_pair and args.label_a == args.label_b:
        parser.error("--label-a and --label-b must differ")

    if args.m0:
        record = run_m0(
            seeds=range(args.seeds),
            n_facts=args.n_facts,
            prior_world1=args.prior_world1,
        )
    elif args.rehearse:
        cells = _cells(_int_list(args.matrix_n_facts), [p for p in args.matrix_prior.split(",") if p])
        record = run_rehearsal(cells=cells, seeds=range(args.seeds))
    else:
        record = pair_reports(
            _load_report(args.report_a),
            _load_report(args.report_b),
            label_a=args.label_a,
            label_b=args.label_b,
        )

    print(_write_out(record, args.out))
    # The M0 pilot is a gate: fail closed if the instrument misses a known answer.
    if args.m0 and not record.get("m0_pass"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
