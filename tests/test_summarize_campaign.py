from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import summarize_campaign  # noqa: E402


def _row(case, env, verdict="PASS", score=1.0, guarantee="behavioral_reference", elapsed=300.0, mode="pass"):
    return {"case_id": case, "environment": env, "status": "scored", "verdict": verdict, "score": score,
            "failure_mode": mode, "judge_guarantee": guarantee, "elapsed_seconds": elapsed, "http_attempts": 40}


def _state(tmp_path: Path, rows, manifest_ids, omitted=()):
    (tmp_path / "suite_checkpoint.json").write_text(json.dumps(
        {"manifest_case_count": len(manifest_ids), "pause_reason": None, "results": rows}))
    (tmp_path / "pilot_manifest.json").write_text(json.dumps({"cases": [{"case_id": c} for c in manifest_ids]}))
    (tmp_path / "campaign_report.json").write_text(json.dumps(
        {"status": "completed", "campaign_omissions": {"omitted_case_ids": list(omitted)}}))


def test_reports_missing_cases_that_are_not_in_an_omission_list(tmp_path, capsys):
    rows = [_row("a", "x"), _row("b", "x")]
    _state(tmp_path, rows, ["a", "b", "c", "d"], omitted=["d"])
    assert summarize_campaign.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "NOT in an omission list: 1" in out and "!! missing: c" in out
    assert "!! missing: d" not in out


def test_flags_perfect_compile_only_and_fast_passes(tmp_path, capsys):
    rows = [_row(f"c{i}", "batchnorm_ema", guarantee="compile_only", elapsed=4.0) for i in range(3)]
    _state(tmp_path, rows, [r["case_id"] for r in rows])
    summarize_campaign.main([str(tmp_path), "--csv", str(tmp_path / "out.csv")])
    out = capsys.readouterr().out
    assert "3/3 PASS under compile_only" in out and "<10s" in out
    assert (tmp_path / "out.csv").read_text().count("\n") == 4


def test_flags_protocol_failures(tmp_path, capsys):
    rows = [_row(f"c{i}", "e", verdict="FAIL", score=0.0, mode="invalid_action") for i in range(4)]
    _state(tmp_path, rows, [r["case_id"] for r in rows])
    summarize_campaign.main([str(tmp_path)])
    assert "failed on protocol/format" in capsys.readouterr().out


def test_unreadable_state_is_an_error(tmp_path):
    assert summarize_campaign.main([str(tmp_path)]) == 2
