"""Paired cross-target comparison for the T1 ``same_fact_presentation`` probe.

This joins two T1 campaign reports -- for example Mercury (Chat Completions,
flat ``reasoning_effort``) and reasoning-Atria (Responses API, nested
``reasoning.effort``) -- on their shared case identities and reports the result
as SEPARATE endpoints per target.

Two disciplines are non-negotiable and enforced here:

* A case is identified by its canonical ``semantic_fact_id`` (structured
  identity derived from the exact fact set, never a hash of rendered text), so
  the same fact set pairs across targets even though each target renders and
  answers it independently.
* The paired result is NEVER collapsed into one susceptibility number and never
  names attention/manipulation/harm. A difference between two targets under
  matched presentation is a behavioral association only. ``assert_reporting_boundary``
  (from :mod:`arena.matched_facts`) is run on every digest before it is returned.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from arena.matched_facts import assert_reporting_boundary

# The canonical diverged-endpoint names produced by
# ``matched_facts.compute_susceptibility``. They are reported separately; the
# digest never sums them into a single score.
DIVERGED_ENDPOINT_NAMES: Tuple[str, ...] = (
    "elicited_belief",
    "elicited_belief_correctness",
    "diagnostic_choices",
    "terminal_outcome",
)
PAIRED_ENDPOINT_NAMES: Tuple[str, ...] = (
    *DIVERGED_ENDPOINT_NAMES,
    "inquiry_regret",
    "recovery",
)

CASE_IDENTITY = "semantic_fact_id"
# The fact-set id alone does NOT identify a task: the same fact set under a
# different prior is a different task with a different correct answer (the prior
# moves the oracle posterior while leaving the canonical facts untouched). The
# case key is therefore the structured pair (fact set, prior) -- still a canonical
# structured identity, never a hash of rendered text.
CASE_KEY = "(semantic_fact_id, prior_world1)"


def _case_key(semantic_fact_id: str, prior_world1: object) -> str:
    if prior_world1 is None:
        return semantic_fact_id
    return f"{semantic_fact_id}@prior={prior_world1}"



def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def flatten_cases(report: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Per-case records keyed by the structured task identity ``(fact set, prior)``.

    Accepts either a ``run_profile`` report (top-level ``cells``, each carrying
    ``trials``) or a single ``run_probe`` report (top-level ``trials``). The key
    combines the canonical ``semantic_fact_id`` with ``prior_world1`` because the
    same fact set under a different prior is a different task (different correct
    answer). Cases without a usable fact identity are skipped, never zero-filled.
    """
    cases: Dict[str, Dict[str, Any]] = {}

    def absorb(trials: object, ctx: Mapping[str, Any]) -> None:
        if not _is_sequence(trials):
            return
        prior = ctx.get("prior_world1")
        for trial in trials:  # type: ignore[union-attr]
            if not isinstance(trial, Mapping):
                continue
            cid = trial.get(CASE_IDENTITY)
            if not isinstance(cid, str) or not cid:
                continue
            susceptibility = trial.get("susceptibility")
            cases[_case_key(cid, prior)] = {
                "case_id": _case_key(cid, prior),
                "semantic_fact_id": cid,
                "prior_world1": prior,
                "seed": trial.get("seed"),
                "n_facts": ctx.get("n_facts", trial.get("fact_count")),
                "oracle_answer": trial.get("oracle_answer"),
                "measurement_status": trial.get("measurement_status"),
                "measurable": trial.get("measurable"),
                "arms": dict(trial.get("arms")) if isinstance(trial.get("arms"), Mapping) else {},
                "susceptibility": dict(susceptibility) if isinstance(susceptibility, Mapping) else {},
            }

    cells = report.get("cells")
    if _is_sequence(cells):
        for cell in cells:  # type: ignore[union-attr]
            if isinstance(cell, Mapping):
                absorb(cell.get("trials"), cell)
    else:
        absorb(report.get("trials"), report)
    return cases


def _diverged(case: Mapping[str, Any]) -> Tuple[str, ...]:
    susceptibility = case.get("susceptibility", {})
    if not isinstance(susceptibility, Mapping):
        return ()
    diverged = susceptibility.get("diverged_endpoints")
    return tuple(diverged) if _is_sequence(diverged) else ()


def _belief_delta(case: Mapping[str, Any]) -> Any:
    susceptibility = case.get("susceptibility", {})
    if not isinstance(susceptibility, Mapping):
        return None
    belief = susceptibility.get("elicited_belief")
    if isinstance(belief, Mapping):
        return belief.get("delta")
    return None


def _case_status(case: Mapping[str, Any]) -> str:
    status = case.get("measurement_status")
    if isinstance(status, str) and status in {"measured", "not_measurable", "unavailable"}:
        return status
    legacy = case.get("measurable")
    if legacy is True:
        return "measured"
    if legacy is False:
        return "not_measurable"
    return "unavailable"


def _endpoint_status(case: Mapping[str, Any], endpoint: str) -> str:
    susceptibility = case.get("susceptibility", {})
    if isinstance(susceptibility, Mapping):
        row = susceptibility.get(endpoint)
        if isinstance(row, Mapping) and isinstance(row.get("status"), str) and row.get("status") in {
            "measured", "not_measurable", "unavailable"
        }:
            return row["status"]
        if endpoint == "elicited_belief_correctness":
            belief = susceptibility.get("elicited_belief")
            if (
                isinstance(belief, Mapping)
                and isinstance(belief.get("status"), str)
                and belief.get("status") in {"measured", "not_measurable", "unavailable"}
            ):
                return belief["status"]
        if endpoint in {"inquiry_regret", "recovery"} and isinstance(row, Mapping):
            if row.get("value") == "not_measurable":
                return "not_measurable"
    # Older report shapes did not state endpoint missingness. Do not infer
    # measurability from an empty delta or a false flip: mark it unavailable.
    return "unavailable"


def target_summary(cases: Mapping[str, Mapping[str, Any]], case_ids: Sequence[str]) -> Dict[str, Any]:
    """One target's endpoint-aware summary over the given case ids."""
    sensitive = 0
    measurable_cases = 0
    not_measurable_cases = 0
    unavailable_cases = 0
    histogram: Dict[str, int] = {}
    belief_deltas: List[str] = []
    belief_delta_status_counts = {"measured": 0, "not_measurable": 0, "unavailable": 0}
    present = 0
    for cid in case_ids:
        case = cases.get(cid)
        if case is None:
            continue
        present += 1
        status = _case_status(case)
        if status == "measured":
            measurable_cases += 1
            diverged = _diverged(case)
            if diverged:
                sensitive += 1
            for endpoint in diverged:
                histogram[endpoint] = histogram.get(endpoint, 0) + 1
        elif status == "not_measurable":
            not_measurable_cases += 1
            diverged = ()
        else:
            # An older or partial report without measurement statuses is
            # unavailable, not silently treated as order-invariant.
            unavailable_cases += 1
            diverged = ()

        delta_status = _endpoint_status(case, "elicited_belief")
        belief_delta_status_counts[delta_status] += 1
        delta = _belief_delta(case)
        if delta_status == "measured" and delta not in (None, "0", 0):
            belief_deltas.append(str(delta))
    return {
        "case_count": present,
        "measurable_cases": measurable_cases,
        "not_measurable_cases": not_measurable_cases,
        "unavailable_cases": unavailable_cases,
        "order_invariant_cases": measurable_cases - sensitive,
        "order_sensitive_cases": sensitive,
        "diverged_endpoint_histogram": histogram,
        "elicited_belief_delta_values": belief_deltas,
        "elicited_belief_delta_status_counts": belief_delta_status_counts,
    }


def _target_meta(report: Mapping[str, Any], label: str) -> Dict[str, Any]:
    """Provenance for one side of the pair, read from the report's target block."""
    target = report.get("target")
    meta: Dict[str, Any] = {"label": label}
    if isinstance(target, Mapping):
        for key in ("provider", "model", "api_base", "wire_api", "reasoning_mode", "reasoning_effort", "kind", "baseline"):
            if target.get(key) is not None:
                meta[key] = target[key]
    return meta


def _paired_endpoint_contrast(
    cases_a: Mapping[str, Mapping[str, Any]],
    cases_b: Mapping[str, Mapping[str, Any]],
    shared: Sequence[str],
    label_a: str,
    label_b: str,
) -> Dict[str, Any]:
    """Per-endpoint paired differences with explicit status denominators."""
    contrast: Dict[str, Any] = {}
    for endpoint in PAIRED_ENDPOINT_NAMES:
        row: Dict[str, Any] = {"shared_case_count": len(shared)}
        for label, cases in ((label_a, cases_a), (label_b, cases_b)):
            status_counts = {"measured": 0, "not_measurable": 0, "unavailable": 0}
            diverged = 0
            for case_id in shared:
                case = cases.get(case_id, {})
                status = _endpoint_status(case, endpoint)
                status_counts[status] += 1
                if status == "measured" and endpoint in _diverged(case):
                    diverged += 1
            if status_counts["measured"]:
                row[label] = {
                    "status": "measured",
                    "diverged_cases": diverged,
                    "measured_cases": status_counts["measured"],
                    "not_measurable_cases": status_counts["not_measurable"],
                    "unavailable_cases": status_counts["unavailable"],
                }
            else:
                missing_status = (
                    "not_measurable"
                    if shared and status_counts["not_measurable"] == len(shared)
                    else "unavailable"
                )
                row[label] = {
                    "status": missing_status,
                    "value": missing_status,
                    "measured_cases": 0,
                    "not_measurable_cases": status_counts["not_measurable"],
                    "unavailable_cases": status_counts["unavailable"],
                }
        contrast[endpoint] = row
    return contrast


def _paired_target_case(case: Mapping[str, Any]) -> Dict[str, Any]:
    status = _case_status(case)
    arms = case.get("arms")
    susceptibility = case.get("susceptibility")
    diverged = _diverged(case) if status == "measured" else ()
    return {
        "measurement_status": status,
        "order_sensitive": bool(diverged) if status == "measured" else status,
        "diverged_endpoints": list(diverged) if status == "measured" else status,
        "arms": dict(arms) if isinstance(arms, Mapping) else {},
        "susceptibility": (
            dict(susceptibility) if isinstance(susceptibility, Mapping) else {}
        ),
    }


def _paired_case(
    cid: str,
    case_a: Mapping[str, Any],
    case_b: Mapping[str, Any],
    label_a: str,
    label_b: str,
) -> Dict[str, Any]:
    return {
        "case_id": cid,
        "seed": case_a.get("seed"),
        "n_facts": case_a.get("n_facts"),
        "prior_world1": case_a.get("prior_world1"),
        "oracle_answer": case_a.get("oracle_answer"),
        "per_target": {
            label_a: _paired_target_case(case_a),
            label_b: _paired_target_case(case_b),
        },
    }


def pair_reports(
    report_a: Mapping[str, Any],
    report_b: Mapping[str, Any],
    *,
    label_a: str,
    label_b: str,
) -> Dict[str, Any]:
    """Join two T1 reports on shared ``semantic_fact_id`` cases.

    Returns a boundary-safe paired digest: per-target summaries over the shared
    cases, a per-endpoint paired contrast, and the per-case paired records. The
    two targets' reasoning mechanisms are carried as separate provenance and are
    never pooled.
    """
    if label_a == label_b:
        raise ValueError("pair labels must differ (they identify the two targets)")
    cases_a = flatten_cases(report_a)
    cases_b = flatten_cases(report_b)
    shared = sorted(set(cases_a) & set(cases_b))
    only_a = sorted(set(cases_a) - set(cases_b))
    only_b = sorted(set(cases_b) - set(cases_a))

    digest: Dict[str, Any] = {
        "digest": "t1_paired_same_fact_presentation",
        "operator": "same_fact_presentation",
        "case_identity": CASE_KEY,
        "targets": {
            "a": _target_meta(report_a, label_a),
            "b": _target_meta(report_b, label_b),
        },
        "measurement_contract": {
            "diagnostic_choices": "per_arm_menu_choices_and_matched_difference",
            "inquiry_regret": "not_measurable_single_turn",
            "elicited_belief": "per_arm_posterior_fraction_and_matched_delta",
            "belief_correctness": "per_case_exact_posterior_match; separate from calibration",
            "calibration_curve": "unavailable_no_population_metric",
            "terminal_outcome": "per_arm_answer_and_correctness",
            "recovery": "not_measurable_single_turn",
            "missingness": "not_measurable_or_unavailable_never_zero_filled",
            "aggregation": "separate_endpoint_channels_no_composite",
        },
        "pairing": {
            "shared_case_count": len(shared),
            "only_a_count": len(only_a),
            "only_b_count": len(only_b),
            "shared_case_ids": shared,
            "only_a_case_ids": only_a,
            "only_b_case_ids": only_b,
        },
        "per_target_shared": {
            label_a: target_summary(cases_a, shared),
            label_b: target_summary(cases_b, shared),
        },
        "paired_endpoints": _paired_endpoint_contrast(cases_a, cases_b, shared, label_a, label_b),
        "paired_cases": [
            _paired_case(cid, cases_a[cid], cases_b[cid], label_a, label_b) for cid in shared
        ],
        "interpretation_boundary": (
            "Paired presentation susceptibility across two targets, reported per "
            "endpoint. A difference between targets under matched presentation is a "
            "behavioral association only: it is not evidence of attention "
            "manipulation, an internal update-rule change, or harm, and the "
            "endpoints are never collapsed into one number. The two targets use "
            "different reasoning mechanisms (see targets provenance) and are not "
            "assumed equivalent."
        ),
    }
    assert_reporting_boundary(digest)
    return digest
