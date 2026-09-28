from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import atria_campaign, run_suite
from tools.campaign_supervisor import decide_tick
from tools.instance_oracle_gate import REFERENCES


REF = "c" * 40
CASE_COUNT = 194


def _old_timestamp() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def _profile() -> dict:
    return {
        "name": "atria_covering_campaign",
        "provider": "atria",
        "model": atria_campaign.APPROVED_MODEL,
        "api_base": atria_campaign.APPROVED_BASE,
        "api_key_env": "ATRIA_API_KEY",
        "matrix": {"mode": "covering", "seeds": [0]},
        "resilience": {
            "provider_outage_patience_seconds": 1,
            "provider_outage_backoff_seconds": 1,
        },
        "unreferenced_compile_only": True,
        "campaign_job_seconds": 600,
        "limits": {
            "max_steps": 1,
            "max_tokens": 8,
            "invalid_retries": 0,
            "max_retries": 0,
            "max_api_calls": CASE_COUNT,
            "max_tokens_total": CASE_COUNT * 8,
            "max_http_attempts": CASE_COUNT + 1,
        },
        "rate_limit": {"min_interval_seconds": 1.1},
        "temperature": 0.0,
        "top_p": 0.95,
    }


def _manifest() -> dict:
    cases = [
        {
            "case_id": f"case-{index}",
            "environment": "categorical_lenses",
            "difficulty": "easy,easy",
            "seed": 0,
        }
        for index in range(CASE_COUNT)
    ]
    return {"ready_for_scheduler": True, "case_count": CASE_COUNT, "cases": cases}


def test_glyph_hard_data_clue_imports_are_allowed_by_its_source_validator() -> None:
    glyph = yaml.safe_load((ROOT / "envs" / "glyph" / "config.yaml").read_text(encoding="utf-8"))
    allowed_imports = glyph["constants"]["%%EXTRA_ALLOWED_IMPORTS%%"]

    # data_clue=hard deliberately embeds the class table through base64/json;
    # without these it fails source validation before either the reference or
    # a plausible-wrong patch can be judged.
    assert '"base64"' in allowed_imports
    assert '"json"' in allowed_imports


def test_gate_wall_reserves_a_whole_exact_instance_case_before_starting_it() -> None:
    # Glyph has its three mandatory variants; SQL also has a transcription
    # variant. The controller must reserve their real judge-timeout envelope,
    # rather than enter a case late and let Actions kill it before its partial
    # checkpoint is persisted.
    glyph_budget = run_suite._gate_case_wall_budget({"environment": "glyph"}, REFERENCES)
    sql_budget = run_suite._gate_case_wall_budget({"environment": "sql_fixed_point"}, REFERENCES)

    assert glyph_budget == 3 * run_suite.GATE_JUDGE_TIMEOUT_SECONDS + run_suite.GATE_CASE_FINISH_RESERVE_SECONDS
    assert sql_budget == 4 * run_suite.GATE_JUDGE_TIMEOUT_SECONDS + run_suite.GATE_CASE_FINISH_RESERVE_SECONDS
    assert glyph_budget < sql_budget
    assert run_suite._gate_case_fits_remaining_wall({"environment": "glyph"}, REFERENCES, glyph_budget)
    assert not run_suite._gate_case_fits_remaining_wall({"environment": "glyph"}, REFERENCES, glyph_budget - 1)


def test_checked_in_covering_profile_is_paid_and_has_the_full_resume_budget() -> None:
    profile = yaml.safe_load((ROOT / "experiments" / "atria_campaign.yaml").read_text(encoding="utf-8"))

    assert profile["provider"] == "atria"
    assert profile["matrix"] == {"mode": "covering", "seeds": [0]}
    assert profile.get("gate_only") is not True
    assert profile["campaign_job_seconds"] == 19_800
    assert profile["limits"]["max_api_calls"] >= CASE_COUNT


def test_one_paid_dispatch_can_cross_gate_and_episode_job_boundaries_to_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model the exact artifact contract used by a two-day covering run.

    The real generation audit exercises all 194 vectors separately. Here the
    expensive provider and judges are replaced only after their handoff points,
    letting this test exercise the controller, persisted artifact state, and
    the actual scheduled-supervisor policy through gate wall, episode wall,
    and completed terminal states.
    """
    output = tmp_path / "atria_campaign"
    output.mkdir()
    (output / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    manifest = _manifest()

    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.setattr(atria_campaign, "build_manifest", lambda **_kwargs: dict(manifest))
    monkeypatch.setattr(atria_campaign, "_apply_gate_blocked_exclusions", lambda *_args: None)
    monkeypatch.setattr(atria_campaign, "_order_cases_referenced_first", lambda *_args: None)
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
        lambda selected: [{"case_id": case["case_id"], "status": "ready"} for case in selected["cases"]],
    )
    monkeypatch.setattr(atria_campaign, "_gate_context_sha", lambda: REF)
    monkeypatch.setattr(atria_campaign, "_runtime_check", lambda: {"available": True})
    monkeypatch.setattr(
        atria_campaign,
        "_optional_credentials",
        lambda *_args, **_kwargs: SimpleNamespace(api_key="not-a-real-key"),
    )
    monkeypatch.setattr(
        atria_campaign,
        "_compatibility_with_patience",
        lambda *_args, **_kwargs: ({"status": "passed"}, 0.0),
    )

    state = {"invocation": 0, "phase": "gate_wall"}

    def checkpoint(*, paused: bool, results: int) -> dict:
        return {
            "run": {"manifest_commit": REF},
            "instance_gate": {
                "gated_case_count": CASE_COUNT,
                "compile_only_case_count": 0,
            },
            "paused": paused,
            "pause_reason": "max_wall_seconds" if paused else None,
            "updated_at": _old_timestamp(),
            "results": [
                {"case_id": f"case-{index}", "status": "scored", "score": 1.0}
                for index in range(results)
            ],
        }

    def fake_run_suite(_selected, **kwargs):
        if kwargs.get("stop_after_gates", False):
            if state["phase"] == "gate_wall":
                (output / "instance_oracles_partial.json").write_text(
                    json.dumps({"rows": {"case-0": {}}}), encoding="utf-8"
                )
                state["phase"] = "episode_wall"
                raise atria_campaign.GateWallExceeded("simulated first-job gate wall")
            # The second and third jobs reuse the saved gate pass.
            return checkpoint(paused=True, results=70)

        if state["phase"] == "episode_wall":
            value = checkpoint(paused=True, results=70)
            (output / "suite_checkpoint.json").write_text(json.dumps(value), encoding="utf-8")
            state["phase"] = "completed"
            return value
        value = checkpoint(paused=False, results=CASE_COUNT)
        (output / "suite_checkpoint.json").write_text(json.dumps(value), encoding="utf-8")
        return value

    monkeypatch.setattr(atria_campaign, "run_suite", fake_run_suite)

    # Manual start: gate exceeds the per-job wall and persists partial state.
    assert atria_campaign.main(
        ["--profile", str(profile_path), "--out", str(output), "--allow-provider"]
    ) == 7
    assert decide_tick(output)["execution_mode"] == "paid"
    assert decide_tick(output)["mode"] == "resume"

    # First scheduled continuation completes the gate and pauses episodes.
    assert atria_campaign.main(
        ["--profile", str(profile_path), "--out", str(output), "--allow-provider"]
    ) == 8
    assert decide_tick(output)["execution_mode"] == "paid"
    assert decide_tick(output)["mode"] == "resume"

    # Next scheduled continuation records all 194 results and terminal state.
    assert atria_campaign.main(
        ["--profile", str(profile_path), "--out", str(output), "--allow-provider"]
    ) == 0
    final = json.loads((output / "campaign_report.json").read_text(encoding="utf-8"))
    assert final["status"] == "completed"
    assert final["recorded_cases"] == CASE_COUNT
    assert decide_tick(output)["mode"] == "none"
