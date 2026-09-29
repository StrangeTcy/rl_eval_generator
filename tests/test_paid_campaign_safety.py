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
from tools.campaign_supervisor import decide_tick


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


def _install_passing_gate(
    monkeypatch: pytest.MonkeyPatch, output: Path
) -> None:
    case = {
        "case_id": "epistemic_games__scenario=trap__seed-0",
        "environment": "epistemic_games",
        "difficulty": "trap",
        "seed": 0,
    }
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
        return {
            "instance_gate": {
                "gated_case_count": 1,
                "compile_only_case_count": 0,
            },
            "run": {},
        }

    monkeypatch.setattr(atria_campaign, "run_suite", fake_run_suite)


def test_passing_gate_still_cannot_reach_paid_phase_without_explicit_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    _install_passing_gate(monkeypatch, output)
    monkeypatch.setattr(
        atria_campaign,
        "_runtime_check",
        lambda: pytest.fail("an ordinary invocation must not inspect Docker"),
    )
    monkeypatch.setattr(
        atria_campaign,
        "_optional_credentials",
        lambda *_args, **_kwargs: pytest.fail("an ordinary invocation must not inspect credentials"),
    )

    result = atria_campaign.main(["--profile", str(profile_path), "--out", str(output)])

    assert result == 3
    report = json.loads((output / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "prepared"
    assert report["pause_reason"] == "provider_access_not_explicitly_allowed"
    assert report["provider_calls"] == 0
    assert report["provider_phase_started"] is False
    marker = json.loads((output / "wrapper_failed.json").read_text(encoding="utf-8"))
    assert marker["pause_reason"] == "provider_access_not_explicitly_allowed"
    intent = json.loads((output / "campaign_intent.json").read_text(encoding="utf-8"))
    assert intent["execution_mode"] == "gates_only"
    assert intent["provider"] == "atria"


def test_deployed_manual_campaign_dispatch_authorizes_paid_phase_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    _install_passing_gate(monkeypatch, output)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Atria covering campaign")
    monkeypatch.setattr(
        atria_campaign,
        "_runtime_check",
        lambda: {"available": False, "reason": "test_docker_unavailable"},
    )
    monkeypatch.setattr(
        atria_campaign,
        "_optional_credentials",
        lambda *_args, **_kwargs: pytest.fail("runtime failure must precede credential inspection"),
    )

    # The published workflow has a ref input and predates --allow-provider.
    # A person pressing its Run workflow button is the explicit initial paid
    # approval; scheduled jobs subsequently recover it only from persisted
    # campaign_intent.json.
    result = atria_campaign.main(["--profile", str(profile_path), "--out", str(output)])

    assert result == 8
    checkpoint = json.loads((output / "suite_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["run"]["provider_access_explicitly_allowed"] is True
    assert checkpoint["pause_reason"] == "docker_unavailable"
    assert checkpoint["runtime_failures"] == 1
    report = json.loads((output / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "paused"
    assert report["resumable"] is True
    intent = json.loads((output / "campaign_intent.json").read_text(encoding="utf-8"))
    assert intent["execution_mode"] == "paid"


def test_allow_provider_records_resumable_paid_authorization_before_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    _install_passing_gate(monkeypatch, output)
    monkeypatch.setattr(
        atria_campaign,
        "_runtime_check",
        lambda: {"available": False, "reason": "test_docker_unavailable"},
    )
    monkeypatch.setattr(
        atria_campaign,
        "_optional_credentials",
        lambda *_args, **_kwargs: pytest.fail("runtime failure must precede credential inspection"),
    )

    result = atria_campaign.main(
        ["--profile", str(profile_path), "--out", str(output), "--allow-provider"]
    )

    assert result == 8
    checkpoint = json.loads((output / "suite_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["run"]["provider_access_explicitly_allowed"] is True
    assert checkpoint["run"]["provider_access_authorized_at"]
    assert checkpoint["pause_reason"] == "docker_unavailable"
    assert checkpoint["runtime_failures"] == 1
    intent = json.loads((output / "campaign_intent.json").read_text(encoding="utf-8"))
    assert intent["execution_mode"] == "paid"


def test_gate_wall_state_is_sufficient_for_a_scheduled_paid_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    output.mkdir()
    (output / "campaign_ref.txt").write_text("test-gate-context\n", encoding="utf-8")
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    _install_passing_gate(monkeypatch, output)

    def wall_limited_gate(_manifest, **kwargs):
        assert kwargs["stop_after_gates"] is True
        (output / "instance_oracles_partial.json").write_text(
            json.dumps({"rows": {"completed-case": {}}}), encoding="utf-8"
        )
        raise atria_campaign.GateWallExceeded("simulated gate wall")

    monkeypatch.setattr(atria_campaign, "run_suite", wall_limited_gate)

    result = atria_campaign.main(
        ["--profile", str(profile_path), "--out", str(output), "--allow-provider"]
    )

    assert result == 7
    report = json.loads((output / "campaign_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "paused"
    assert report["pause_reason"] == "max_wall_seconds"
    assert report["resumable"] is True
    decision = decide_tick(output)
    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == "test-gate-context"


def test_deployed_launcher_can_run_the_documented_paid_controller_revision() -> None:
    deployed = (ROOT / ".github" / "workflows" / "atria-campaign.yml").read_text(encoding="utf-8")
    documented_controller = (ROOT / "docs" / "workflows" / "atria-campaign.yml.example").read_text(encoding="utf-8")
    deployed_inputs = yaml.load(deployed, Loader=yaml.BaseLoader)["on"]["workflow_dispatch"]["inputs"]
    documented_inputs = yaml.load(documented_controller, Loader=yaml.BaseLoader)["on"]["workflow_dispatch"]["inputs"]

    # The launcher accepts a pinned ref. That lets a manual dispatch run the
    # tested controller on this branch without first needing to modify a
    # protected .github/workflows path. Its bootstrap artifact exists before
    # setup so a setup-host failure can be resumed by the scheduler.
    assert "ref" in deployed_inputs
    assert "ref" in documented_inputs
    assert "actions/checkout@v4" in deployed
    assert "ref: ${{ steps.mode.outputs.ref }}" in deployed
    assert "python tools/atria_campaign.py" in deployed
    # The checked-in documentation copy is the deployable replacement for the
    # protected workflow path. It adds pre-setup bootstrap state and the same
    # resumable reasons used by the controller.
    assert "campaign_bootstrap.json" in documented_controller
    assert "wrapper_transient_error" in documented_controller
    assert "WANDB_API_KEY" in documented_controller
    assert "Install optional W&B campaign telemetry" in documented_controller
    assert "issues: write" in documented_controller
    assert "campaign_status_sidecar.py" in documented_controller
    assert "--wait-for-path runs/atria_campaign/campaign_intent.json" in documented_controller
    supervisor = (ROOT / "tools" / "campaign_supervisor.py").read_text(encoding="utf-8")
    assert "campaign_intent.json" in supervisor
    assert "campaign_bootstrap.json" in supervisor

