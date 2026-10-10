from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.campaign_progress import write_progress  # noqa: E402
from tools.campaign_status_sidecar import _body  # noqa: E402


def test_sidecar_reports_t1_calls_and_cells_without_collapsing_endpoints(tmp_path: Path) -> None:
    write_progress(
        tmp_path,
        progress_kind="t1_same_fact_presentation",
        phase="T1 same_fact_presentation",
        current_case="n_facts=4, prior_world1=1/2",
        t1_api_calls_completed=96,
        t1_api_calls_total=288,
        t1_cells_completed=2,
        t1_cells_total=6,
    )

    body = _body(tmp_path)

    assert "T1 matched-arm calls:** `96 / 288`" in body
    assert "T1 matched cells:** `2 / 6`" in body
    assert "persisted campaign metadata only" in body


def test_sidecar_marks_interrupted_t1_as_operator_review_not_replay(tmp_path: Path) -> None:
    (tmp_path / "t1_interrupted.json").write_text(
        '{"status":"interrupted","resume_policy":"operator_review_required_no_replay"}',
        encoding="utf-8",
    )

    body = _body(tmp_path)

    assert "T1 status:** `interrupted; operator review required; no automatic replay`" in body
