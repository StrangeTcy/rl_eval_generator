from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import atria_campaign


def _profile() -> dict:
    return {
        "name": "atria_covering_campaign",
        "provider": "atria",
        "model": atria_campaign.APPROVED_MODEL,
        "api_base": atria_campaign.APPROVED_BASE,
        "api_key_env": "ATRIA_API_KEY",
        "matrix": {"mode": "covering", "seeds": [0]},
        "resilience": {
            "provider_outage_patience_seconds": 60,
            "provider_outage_backoff_seconds": 1,
        },
        "unreferenced_compile_only": True,
        "campaign_job_seconds": 600,
        "limits": {
            "max_steps": 1,
            "max_tokens": 8,
            "invalid_retries": 0,
            "max_retries": 0,
            "max_api_calls": 1,
            "max_tokens_total": 16,
            "max_http_attempts": 2,
        },
        "rate_limit": {"min_interval_seconds": 1.1},
        "temperature": 0.0,
        "top_p": 0.95,
    }


@pytest.mark.parametrize("use_profile_switch", [False, True])
def test_gate_only_clears_stale_dispatch_state_and_never_enters_paid_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_profile_switch: bool,
) -> None:
    output = tmp_path / "atria_campaign"
    output.mkdir()
    (output / "campaign_ref.txt").write_text("main\n", encoding="utf-8")
    (output / "suite_checkpoint.json").write_text(
        json.dumps({"manifest_case_count": 5, "run": {"provider": "custom"}}),
        encoding="utf-8",
    )
    (output / "instance_oracles_partial.json").write_text(
        json.dumps({"gate_context_sha": "rehearsal-context-sha", "rows": {}}),
        encoding="utf-8",
    )
    (output / "campaign_report.json").write_text(
        json.dumps({"status": "completed", "event": "rehearsal_campaign"}),
        encoding="utf-8",
    )
    profile_path = tmp_path / "profile.yaml"
    profile = _profile()
    if use_profile_switch:
        profile["gate_only"] = True
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")

    case = {
        "case_id": "epistemic_games__scenario=trap__seed-0",
        "environment": "epistemic_games",
        "difficulty": "trap",
        "seed": 0,
    }
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(
        atria_campaign,
        "build_manifest",
        lambda **_kwargs: {
            "ready_for_scheduler": True,
            "case_count": 1,
            "cases": [dict(case)],
        },
    )
    monkeypatch.setattr(atria_campaign, "_order_cases_referenced_first", lambda _manifest: None)
    monkeypatch.setattr(
        atria_campaign,
        "inventory_selected_modalities",
        lambda *_args, **_kwargs: {
            "unsupported_case_ids": [],
            "all_selected_cases_text_only_compatible": True,
        },
    )
    monkeypatch.setattr(
        atria_campaign,
        "_generation_preflight",
        lambda _manifest: [{"case_id": case["case_id"], "status": "ready"}],
    )
    monkeypatch.setattr(atria_campaign, "_gate_context_sha", lambda: "test-gate-context")

    def fake_run_suite(_manifest, **kwargs):
        assert kwargs["stop_after_gates"] is True
        assert kwargs["checkpoint_path"] == output / "suite_checkpoint.json"
        return {"instance_gate": {"gated_case_count": 1, "compile_only_case_count": 0}}

    monkeypatch.setattr(atria_campaign, "run_suite", fake_run_suite)
    monkeypatch.setattr(
        atria_campaign,
        "_runtime_check",
        lambda: pytest.fail("gate-only mode must not check Docker or start the paid phase"),
    )
    monkeypatch.setattr(
        atria_campaign,
        "_optional_credentials",
        lambda *_args, **_kwargs: pytest.fail("gate-only mode must not inspect provider credentials"),
    )

    argv = ["--profile", str(profile_path), "--out", str(output)]
    if not use_profile_switch:
        argv.append("--gates-only")
    result = atria_campaign.main(argv)

    assert result == 0
    assert (output / "campaign_ref.txt").read_text(encoding="utf-8") == "main\n"
    assert not (output / "instance_oracles_partial.json").exists()
    assert not (output / "suite_checkpoint.json").exists()
    report = json.loads((output / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "gate_passed"
    assert report["provider_calls"] == 0
    assert report["provider_phase_started"] is False


def test_campaign_failure_artifact_names_blocking_gate_case_and_replaces_stale_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "atria_campaign"
    output.mkdir()
    (output / "campaign_ref.txt").write_text("main\n", encoding="utf-8")
    (output / "suite_checkpoint.json").write_text(
        json.dumps({"manifest_case_count": 5, "run": {"provider": "custom"}}),
        encoding="utf-8",
    )
    (output / "campaign_report.json").write_text(
        json.dumps({"status": "completed", "event": "rehearsal_campaign"}),
        encoding="utf-8",
    )
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    case = {
        "case_id": "moco__naming=hard__seed-0",
        "environment": "moco",
        "difficulty": "hard",
        "seed": 0,
    }
    failed_row = {
        "case_id": case["case_id"],
        "environment": "moco",
        "status": "blocked",
        "reason": "reference_did_not_grade_as_expected",
        "variants": [{
            "variant": "reference",
            "accepted": False,
            "verdict": "FAIL",
            "failure_mode": "fail",
            "checks": {"temperature_sensitive": False},
            "stderr_tail": "oracle failure detail",
        }],
    }

    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(
        atria_campaign,
        "build_manifest",
        lambda **_kwargs: {
            "ready_for_scheduler": True,
            "case_count": 1,
            "cases": [dict(case)],
        },
    )
    monkeypatch.setattr(atria_campaign, "_order_cases_referenced_first", lambda _manifest: None)
    monkeypatch.setattr(
        atria_campaign,
        "inventory_selected_modalities",
        lambda *_args, **_kwargs: {
            "unsupported_case_ids": [],
            "all_selected_cases_text_only_compatible": True,
        },
    )
    monkeypatch.setattr(
        atria_campaign,
        "_generation_preflight",
        lambda _manifest: [{"case_id": case["case_id"], "status": "ready"}],
    )
    monkeypatch.setattr(atria_campaign, "_gate_context_sha", lambda: "test-gate-context")

    def fake_run_suite(_manifest, **kwargs):
        assert kwargs["stop_after_gates"] is True
        (output / "instance_oracles.json").write_text(
            json.dumps({"instance_coverage_complete": False, "cases": [failed_row]}),
            encoding="utf-8",
        )
        raise ValueError(
            "exact-instance behavioral oracle coverage is incomplete; inspect instance_oracles.json"
        )

    monkeypatch.setattr(atria_campaign, "run_suite", fake_run_suite)
    monkeypatch.setattr(
        atria_campaign,
        "_runtime_check",
        lambda: pytest.fail("a blocked gate must not reach Docker or the paid phase"),
    )
    monkeypatch.setattr(
        atria_campaign,
        "_optional_credentials",
        lambda *_args, **_kwargs: pytest.fail("a blocked gate must not inspect provider credentials"),
    )

    result = atria_campaign.main(["--profile", str(profile_path), "--out", str(output)])

    assert result == 2
    wrapper = json.loads((output / "wrapper_failed.json").read_text(encoding="utf-8"))
    report = json.loads((output / "campaign_report.json").read_text(encoding="utf-8"))
    assert wrapper["pause_reason"] == "instance_oracle_coverage_incomplete"
    assert case["case_id"] in wrapper["detail"]
    assert report["status"] == "blocked"
    assert report["provider_calls"] == 0
    assert report["diagnostics"]["exact_instance_failed_cases"][0]["case_id"] == case["case_id"]
    assert not (output / "suite_checkpoint.json").exists()


def test_campaign_failure_diagnostics_name_failed_exact_instance_and_variant(
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "generation_preflight.json").write_text(
        json.dumps({"cases": [{"case_id": "gen-bad", "status": "generation_error", "error": "missing template"}]}),
        encoding="utf-8",
    )
    (output / "instance_oracles.json").write_text(
        json.dumps({
            "instance_coverage_complete": False,
            "cases": [
                {"case_id": "good", "status": "passed", "variants": []},
                {
                    "case_id": "moco__naming=hard__seed-0",
                    "environment": "moco",
                    "status": "blocked",
                    "reason": "reference_did_not_grade_as_expected",
                    "variants": [{
                        "variant": "reference",
                        "accepted": False,
                        "verdict": "FAIL",
                        "failure_mode": "fail",
                        "checks": {"temperature_sensitive": False},
                        "stderr_tail": "safe diagnostic",
                    }],
                },
            ],
        }),
        encoding="utf-8",
    )

    diagnostics = atria_campaign._campaign_failure_diagnostics(output)
    formatted = atria_campaign._format_failure_diagnostics(diagnostics)

    assert [row["case_id"] for row in diagnostics["generation_preflight_failed_cases"]] == ["gen-bad"]
    assert [row["case_id"] for row in diagnostics["exact_instance_failed_cases"]] == [
        "moco__naming=hard__seed-0"
    ]
    assert diagnostics["exact_instance_failed_cases"][0]["failed_variants"][0]["checks"] == {
        "temperature_sensitive": False
    }
    assert "moco__naming=hard__seed-0" in formatted
    assert "reference_did_not_grade_as_expected" in formatted


def test_report_distinguishes_resumable_infrastructure_retry_from_exhaustion() -> None:
    common = {
        "results": [],
        "instance_gate": {"gated_case_count": 194, "compile_only_case_count": 0},
    }
    retrying = atria_campaign._report_from_checkpoint(
        common,
        compatibility=None,
        compat_waited=0,
        status="paused",
        pause_reason="infrastructure_error",
    )
    exhausted = atria_campaign._report_from_checkpoint(
        common,
        compatibility=None,
        compat_waited=0,
        status="paused",
        pause_reason="infrastructure_error_retries_exhausted",
    )

    assert retrying["resumable"] is True
    assert exhausted["resumable"] is False


def test_fresh_output_reset_refuses_to_remove_unrecognized_directory(tmp_path: Path) -> None:
    unrelated = tmp_path / "valuable-data"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="recognizable campaign state"):
        atria_campaign._reset_fresh_campaign_output(unrelated)

    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_blocked_gate_rows_are_reported_by_group_so_a_cut_log_cannot_lose_a_class() -> None:
    """A listing capped at twenty rows per category is how a blocked campaign read as a small one.

    The log named 14 rows while the artifact held 49, and every reading of that sample was a guess
    about the rest. The shape of a failure set - which reason, on which axis levels, how many - is
    what an omission list has to be written from, and it is bounded, so it is what the summary leads
    with.
    """
    rows = [
        {
            "case_id": f"moco__naming={'hard' if index % 2 else 'medium'}_distractors=easy_"
                       "queue_math=easy_temperature=easy_visible_tests=easy_symptom_mask=easy__seed-0",
            "status": "blocked",
            "reason": "oracle_error",
        }
        for index in range(35)
    ] + [
        {
            "case_id": "glyph__architecture=hard_optimizer=hard_red_herring=easy_visible_tests=easy"
                       "_data_clue=medium_symptom_mask=medium__seed-0",
            "status": "blocked",
            "reason": "plausible_wrong_did_not_grade_as_expected",
        }
    ] * 8

    formatted = atria_campaign._format_failure_diagnostics({"exact_instance_failed_cases": rows})

    assert "43 blocked exact-instance oracle row(s), 3 group(s):" in formatted
    assert "oracle_error x18 on naming=medium" in formatted
    assert "oracle_error x17 on naming=hard" in formatted
    assert "plausible_wrong_did_not_grade_as_expected x8 on architecture=hard" in formatted
    # axis names contain underscores, so a naive split reported `mask=medium` for `symptom_mask=medium`
    assert "symptom_mask=medium" in formatted
    assert "calibration_class: reference_not_configured_for_this_vector" in formatted


def test_more_groups_than_fit_are_counted_rather_than_dropped() -> None:
    rows = [
        {
            "case_id": f"glyph__ax{index:02d}=hard_optimizer=medium_red_herring=easy__seed-0",
            "status": "blocked",
            "reason": "reference_did_not_grade_as_expected",
        }
        for index in range(30)
    ]

    formatted = atria_campaign._format_failure_diagnostics({"exact_instance_failed_cases": rows})

    assert "30 blocked exact-instance oracle row(s), 30 group(s):" in formatted
    assert "+5 further group(s) covering 5 row(s)" in formatted


def test_a_state_contract_refusal_does_not_write_the_gate_it_cannot_pass(tmp_path: Path) -> None:
    """Five Mercury legs inherited a marker whose only cause was the leg before it.

    The marker means "an operator must acknowledge", and the acknowledgement the launcher accepts covers
    a harness crash - never a contract refusal, which repeats byte-identically. So the first one is
    recorded and leaves the state reachable by a plain dispatch; a second, at the same commit, with the
    same detail, is a fix that did not take and re-arms the gate.
    """
    detail = (
        "checkpoint metadata mismatch for manifest_commit: "
        "'0ddcd396b45f46b9fbbba7d477b34221a3724ef2' != '5cb4205ae3f69c72809e4834e52006b3406fb3a7'"
    )
    assert atria_campaign._state_contract_stop(tmp_path, detail) is False
    assert (tmp_path / "state_contract_stop.json").is_file()
    assert not (tmp_path / "wrapper_failed.json").exists()

    # A genuine crash still gates, unchanged.
    assert atria_campaign._state_contract_stop(tmp_path, "TypeError: unsupported operand") is True

    # Same detail, same code: the second leg escalates. (The commit identity is what makes this a
    # "nothing changed" test rather than a "this string exists somewhere in history" test.)
    first = json.loads((tmp_path / "state_contract_stop.json").read_text(encoding="utf-8"))
    recorded = {**first, "at_commit": "0" * 40, "detail": detail, "count": 1}
    (tmp_path / "state_contract_stop.json").write_text(json.dumps(recorded), encoding="utf-8")
    assert atria_campaign._state_contract_stop(tmp_path, detail) is False
    after = json.loads((tmp_path / "state_contract_stop.json").read_text(encoding="utf-8"))
    assert after["count"] == 1, after  # a different commit resets the counter

    # Same detail, same commit, twice in a row: gate an operator.
    same = {**after, "at_commit": after["at_commit"], "count": 1}
    (tmp_path / "state_contract_stop.json").write_text(json.dumps(same), encoding="utf-8")
    assert atria_campaign._state_contract_stop(tmp_path, detail) is True
    assert json.loads((tmp_path / "state_contract_stop.json").read_text(encoding="utf-8"))["count"] == 2
