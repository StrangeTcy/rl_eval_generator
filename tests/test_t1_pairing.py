"""Offline tests for the paired T1 digest, M0 pilot, and rehearsal.

These never touch the network: they drive the deterministic baselines through the
real harness (run_probe) and assert the pairing contract -- canonical case
identity, shared-case join, separately-reported endpoints, and the reporting
boundary. The M0 known-answer pilot and the rehearsal both produce real numbers
offline, which is the point: the instrument and the reporting chain are proven
before any provider token is spent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.matched_facts import assert_reporting_boundary  # noqa: E402
from arena.t1_pairing import flatten_cases, pair_reports  # noqa: E402
from tools.t1_paired_report import (  # noqa: E402
    M0_EXPECTATIONS,
    _baseline_report,
    run_m0,
    run_rehearsal,
)

# Same n_facts, two priors: exercises the composite (fact set, prior) case key.
CELLS = [(4, "1/2"), (4, "1/3")]


def test_flatten_separates_identical_facts_under_different_priors() -> None:
    # Regression: one fact set under two priors is TWO tasks (different correct
    # answer), so it must flatten to two cases, not collapse onto the fact id.
    report = _baseline_report("t", "exact_oracle", cells=CELLS, seeds=[0, 1])
    cases = flatten_cases(report)
    assert len(cases) == 4  # 2 priors x 2 seeds
    fact_ids = {c["semantic_fact_id"] for c in cases.values()}
    assert len(fact_ids) == 2  # the fact set repeats across the two priors
    priors = {c["prior_world1"] for c in cases.values()}
    assert priors == {"1/2", "1/3"}
    # Every case id carries the prior so the join cannot silently merge them.
    assert all("@prior=" in cid for cid in cases)


def test_flatten_accepts_a_single_run_probe_report_shape() -> None:
    from tools.matched_fact_probe import BASELINES, run_probe

    probe_report = run_probe(BASELINES["exact_oracle"], seeds=[0, 1, 2], n_facts=4)
    cases = flatten_cases(probe_report)
    assert len(cases) == 3
    assert all(c["prior_world1"] == "1/2" for c in cases.values())


def test_flatten_skips_cases_without_a_fact_identity() -> None:
    report = {
        "trials": [
            {"seed": 0, "susceptibility": {}},                 # no semantic_fact_id
            {"seed": 1, "semantic_fact_id": "", "susceptibility": {}},  # empty id
        ]
    }
    assert flatten_cases(report) == {}


def test_pair_joins_shared_cases_and_keeps_endpoints_separate() -> None:
    rep_a = _baseline_report("robust", "exact_oracle", cells=CELLS, seeds=[0, 1, 2, 3])
    rep_b = _baseline_report("sensitive", "primacy_biased", cells=CELLS, seeds=[0, 1, 2, 3])
    digest = pair_reports(rep_a, rep_b, label_a="robust", label_b="sensitive")

    assert digest["pairing"]["shared_case_count"] == 8  # 2 priors x 4 seeds
    assert digest["pairing"]["only_a_count"] == 0
    assert digest["pairing"]["only_b_count"] == 0

    a = digest["per_target_shared"]["robust"]
    b = digest["per_target_shared"]["sensitive"]
    assert a["order_sensitive_cases"] == 0          # exact_oracle is order-invariant
    assert a["order_invariant_cases"] == 8
    assert b["order_sensitive_cases"] > 0           # primacy is order-sensitive

    # Endpoints stay separate; nothing is collapsed into one blended number.
    endpoints = digest["paired_endpoints"]
    assert {"elicited_belief", "elicited_belief_correctness", "diagnostic_choices", "terminal_outcome"} <= set(endpoints)
    assert endpoints["inquiry_regret"]["robust"]["status"] == "not_measurable"
    assert endpoints["inquiry_regret"]["robust"]["value"] == "not_measurable"
    assert endpoints["inquiry_regret"]["robust"]["not_measurable_cases"] == 8
    assert endpoints["recovery"]["sensitive"]["status"] == "not_measurable"
    assert endpoints["recovery"]["sensitive"]["value"] == "not_measurable"
    assert endpoints["recovery"]["sensitive"]["not_measurable_cases"] == 8
    for name, row in endpoints.items():
        if name in {"inquiry_regret", "recovery"}:
            continue
        assert isinstance(row["robust"], dict) and "diverged_cases" in row["robust"]
        assert isinstance(row["sensitive"], dict) and "diverged_cases" in row["sensitive"]
    assert digest["measurement_contract"]["calibration_curve"] == "unavailable_no_population_metric"
    first_pair = digest["paired_cases"][0]["per_target"]
    assert "arms" in first_pair["robust"] and "susceptibility" in first_pair["robust"]
    assert first_pair["robust"]["arms"]["a"]["inquiry_regret"] == "not_measurable"

    assert_reporting_boundary(digest)  # must not raise


def test_unmeasured_cases_are_not_counted_as_order_invariant_or_zero_delta() -> None:
    def report(label: str) -> dict:
        return {
            "target": {"provider": label, "model": "offline"},
            "cells": [{
                "n_facts": 3,
                "prior_world1": "1/2",
                "trials": [{
                    "semantic_fact_id": "semantic-case-1",
                    "seed": 0,
                    "measurement_status": "not_measurable",
                    "measurable": False,
                    "arms": {
                        "a": {"elicited_belief": None, "inquiry_regret": "not_measurable", "recovery": "not_measurable"},
                        "b": {"elicited_belief": None, "inquiry_regret": "not_measurable", "recovery": "not_measurable"},
                    },
                    "susceptibility": {
                        "elicited_belief": {"status": "not_measurable", "delta": "not_measurable"},
                        "elicited_belief_correctness": {"status": "not_measurable", "correctness_flip": "not_measurable"},
                        "diagnostic_choices": {"status": "not_measurable", "symmetric_difference": "not_measurable"},
                        "terminal_outcome": {"status": "not_measurable", "answer_flip": "not_measurable", "correctness_flip": "not_measurable"},
                        "inquiry_regret": {"status": "not_measurable", "value": "not_measurable"},
                        "recovery": {"status": "not_measurable", "value": "not_measurable"},
                        "diverged_endpoints": [],
                    },
                }],
            }],
        }

    digest = pair_reports(report("a"), report("b"), label_a="a", label_b="b")
    summary = digest["per_target_shared"]["a"]
    assert summary["case_count"] == 1
    assert summary["not_measurable_cases"] == 1
    assert summary["order_invariant_cases"] == 0
    assert summary["order_sensitive_cases"] == 0
    assert summary["elicited_belief_delta_values"] == []
    assert summary["elicited_belief_delta_status_counts"]["not_measurable"] == 1
    assert digest["paired_cases"][0]["per_target"]["a"]["measurement_status"] == "not_measurable"
    assert_reporting_boundary(digest)


def test_unavailable_endpoint_is_not_reported_as_zero_divergence() -> None:
    def report(label: str) -> dict:
        return {
            "target": {"provider": label, "model": "offline"},
            "cells": [{
                "prior_world1": "1/2",
                "trials": [{
                    "semantic_fact_id": "semantic-case-unavailable",
                    "seed": 0,
                    "measurement_status": "unavailable",
                    "measurable": False,
                    "arms": {"a": {}, "b": {}},
                    "susceptibility": {
                        "elicited_belief": {"status": "unavailable", "delta": "unavailable"},
                        "elicited_belief_correctness": {"status": "unavailable", "correctness_flip": "unavailable"},
                        "diagnostic_choices": {"status": "unavailable", "symmetric_difference": "unavailable"},
                        "terminal_outcome": {"status": "unavailable", "answer_flip": "unavailable", "correctness_flip": "unavailable"},
                        "inquiry_regret": {"status": "not_measurable", "value": "not_measurable"},
                        "recovery": {"status": "not_measurable", "value": "not_measurable"},
                        "diverged_endpoints": [],
                    },
                }],
            }],
        }

    digest = pair_reports(report("a"), report("b"), label_a="a", label_b="b")
    summary = digest["per_target_shared"]["a"]
    assert summary["unavailable_cases"] == 1
    assert summary["order_invariant_cases"] == 0
    endpoint = digest["paired_endpoints"]["elicited_belief"]["a"]
    assert endpoint["status"] == "unavailable"
    assert endpoint["value"] == "unavailable"
    assert endpoint["measured_cases"] == 0
    assert_reporting_boundary(digest)


def test_pair_reports_only_ids_when_matrices_differ() -> None:
    rep_a = _baseline_report("a", "exact_oracle", cells=[(4, "1/2")], seeds=[0, 1])
    rep_b = _baseline_report("b", "exact_oracle", cells=[(4, "1/2")], seeds=[1, 2])
    digest = pair_reports(rep_a, rep_b, label_a="a", label_b="b")
    # seed 1 is shared; seed 0 only in a, seed 2 only in b.
    assert digest["pairing"]["shared_case_count"] == 1
    assert digest["pairing"]["only_a_count"] == 1
    assert digest["pairing"]["only_b_count"] == 1


def test_pair_reports_rejects_identical_labels() -> None:
    rep = _baseline_report("x", "exact_oracle", cells=CELLS, seeds=[0])
    with pytest.raises(ValueError):
        pair_reports(rep, rep, label_a="same", label_b="same")


def test_m0_known_answer_pilot_passes_offline() -> None:
    record = run_m0(seeds=range(8))
    assert record["m0_pass"] is True
    by_name = {b["baseline"]: b for b in record["baselines"]}
    assert set(by_name) == set(M0_EXPECTATIONS)
    # Order-invariant baselines: the metric must stay silent (zero sensitive).
    assert by_name["exact_oracle"]["order_sensitive_trials"] == 0
    assert by_name["prior_anchored"]["order_sensitive_trials"] == 0
    # Order-sensitive baselines: the metric must fire.
    assert by_name["primacy_biased"]["order_sensitive_trials"] > 0
    assert by_name["recency_biased"]["order_sensitive_trials"] > 0
    assert_reporting_boundary(record)


def test_rehearsal_produces_a_real_paired_digest_offline() -> None:
    digest = run_rehearsal(cells=CELLS, seeds=range(6))
    assert digest["pairing"]["shared_case_count"] == 12  # 2 priors x 6 seeds
    robust = digest["per_target_shared"]["stand_in_robust"]
    sensitive = digest["per_target_shared"]["stand_in_order_sensitive"]
    assert robust["order_sensitive_cases"] == 0
    assert sensitive["order_sensitive_cases"] > robust["order_sensitive_cases"]
    assert digest["rehearsal"]["stand_in_a"]["baseline"] == "exact_oracle"
    assert digest["rehearsal"]["stand_in_b"]["baseline"] == "primacy_biased"
    assert_reporting_boundary(digest)


def test_m0_gate_fails_closed_when_a_known_answer_is_violated(monkeypatch) -> None:
    import tools.t1_paired_report as tpr

    # Force a wrong expectation: exact_oracle is order-INVARIANT by construction,
    # so demanding order_sensitive must make the pilot fail and the CLI exit 1.
    monkeypatch.setitem(tpr.M0_EXPECTATIONS, "exact_oracle", "order_sensitive")
    record = tpr.run_m0(seeds=range(4))
    assert record["m0_pass"] is False
    assert tpr.main(["--m0", "--seeds", "4"]) == 1


def test_cli_pairs_two_report_files_and_writes_the_digest(tmp_path) -> None:
    import json

    import tools.t1_paired_report as tpr

    rep_a = _baseline_report("mercury", "exact_oracle", cells=CELLS, seeds=[0, 1])
    rep_b = _baseline_report("atria", "primacy_biased", cells=CELLS, seeds=[0, 1])
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(rep_a))
    pb.write_text(json.dumps(rep_b))
    out = tmp_path / "digest.json"
    rc = tpr.main(
        [
            "--report-a", str(pa), "--report-b", str(pb),
            "--label-a", "mercury", "--label-b", "atria", "--out", str(out),
        ]
    )
    assert rc == 0
    digest = json.loads(out.read_text())
    assert digest["pairing"]["shared_case_count"] == 4  # 2 priors x 2 seeds
    assert digest["targets"]["a"]["label"] == "mercury"
    assert digest["targets"]["b"]["label"] == "atria"


def test_cli_requires_exactly_one_mode() -> None:
    import tools.t1_paired_report as tpr

    with pytest.raises(SystemExit):
        tpr.main([])  # no mode chosen
