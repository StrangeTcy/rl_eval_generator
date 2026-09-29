from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import campaign_telemetry


def test_telemetry_is_disabled_without_wandb_secret_and_persists_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    (tmp_path / "campaign_ref.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    (tmp_path / "campaign_intent.json").write_text(
        json.dumps({"provider": "atria", "execution_mode": "paid"}), encoding="utf-8"
    )

    first = campaign_telemetry.CampaignTelemetry(tmp_path)
    first.log(telemetry_phase="episodes", episodes_current_case="case-1")
    second = campaign_telemetry.CampaignTelemetry(tmp_path)

    assert first.enabled is False
    assert first.run_id == second.run_id
    state = json.loads((tmp_path / "campaign_telemetry.json").read_text(encoding="utf-8"))
    assert state["wandb_run_id"] == first.run_id
    assert "WANDB_API_KEY" not in (tmp_path / "campaign_telemetry.json").read_text(encoding="utf-8")


def test_external_payload_filter_rejects_non_scalar_values() -> None:
    assert campaign_telemetry._scalar_payload(
        {"safe": "case-1", "count": 3, "secret_like": {"nested": "not sent"}, "list": [1]}
    ) == {"safe": "case-1", "count": 3}
