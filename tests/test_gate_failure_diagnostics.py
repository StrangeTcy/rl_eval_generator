"""The gate has to say what it saw, not only that it disagreed.

A leg of the Reasoning-Atria campaign blocked on 12 glyph rows with
``reference_did_not_grade_as_expected``. That reason is produced both when the reference
model simply did not reach a perfect score and when the reference program is broken, and
the two have opposite repairs - raise the training budget, or fix the splice. Before this,
the campaign log carried only the reason and the axis levels, so the next leg had to be
spent to find out which one it was.

These tests pin the two halves of the fix: `validate_case` persists the judge's actual
verdict, score, failing checks and notes on the blocked row, and the campaign summary
prints them per group and announces the character cut instead of performing it quietly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402  (root module, not tools/)

from tools import atria_campaign, instance_oracle_gate  # noqa: E402


# ---------------------------------------------------------------- gate row
def _blocked_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, judge: dict) -> dict:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "train.py").write_text("optimizer = optim.SGD(model.parameters(), lr=1e-4)\n", encoding="utf-8")
    original = tmp_path / "original"
    original.mkdir()
    (original / "train.py").write_text("optimizer = optim.SGD(model.parameters(), lr=1e-4)\n", encoding="utf-8")
    env_dir = tmp_path / "env"
    (env_dir / "judge").mkdir(parents=True)

    state = {
        "workspace": str(workspace),
        "original_workspace": str(original),
        "env_dir": str(env_dir),
        "episode_dir": str(tmp_path / "episode"),
    }
    (tmp_path / "episode").mkdir()
    monkeypatch.setattr(
        instance_oracle_gate, "REFERENCES", {"fake_env": (lambda ws, *, wrong: None, "any_check")}
    )
    monkeypatch.setattr(env_runner, "reset", lambda args: None)
    monkeypatch.setattr(env_runner, "_load_state", lambda episode_id: dict(state))
    monkeypatch.setattr(
        env_runner, "_submit",
        lambda state, action, judge_timeout=0: (None, judge["score"], True, {"judge_result": judge, "judge_stderr": judge.get("stderr", "")}),
    )
    return instance_oracle_gate.validate_case(
        {"case_id": "fake_env__x=hard__seed-0", "environment": "fake_env", "difficulty": "hard", "seed": 0},
        root=ROOT,
        include_slow=True,
    )


def test_a_blocked_row_records_what_the_judge_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    row = _blocked_row(tmp_path, monkeypatch, {
        "score": 0.85,
        "raw_accuracy": 0.85,
        "verdict": "FAIL",
        "failure_mode": "overfit_spatial_layout",
        "checks": {"patch_valid": True, "spatial_layout_invariant": False},
        "notes": ["reference memorised the training-resolution layout"],
        "stderr": "Traceback: nothing fatal, just weak",
    })
    assert row["status"] == "blocked"
    assert row["reason"].endswith("_did_not_grade_as_expected"), row
    observed = row["observed"]
    assert observed["verdict"] == "FAIL" and observed["score"] == 0.85
    assert observed["failure_mode"] == "overfit_spatial_layout"
    assert observed["failed_checks"] == ["spatial_layout_invariant"], (
        "the check that failed is the actionable part"
    )
    assert observed["notes"] == ["reference memorised the training-resolution layout"]
    assert observed["variant"] == row["reason"].split("_did_not")[0]


def test_a_row_still_blocks_when_the_judge_returned_nothing_useful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _blocked_row(tmp_path, monkeypatch, {"score": None, "verdict": None, "checks": {}})
    assert row["status"] == "blocked" and "observed" in row
    assert row["observed"]["failed_checks"] == []


# ---------------------------------------------------------------- summary
def _failures(count: int, *, observed: dict | None = None) -> list[dict]:
    rows = []
    for index in range(count):
        row = {
            "case_id": f"glyph__architecture=hard_optimizer=hard_red_herring=hard_visible_tests=hard_data_clue=hard_symptom_mask=hard__seed-{index}",
            "reason": "reference_did_not_grade_as_expected",
            "status": "blocked",
        }
        if observed is not None:
            row["observed"] = observed
        rows.append(row)
    return rows


def test_the_summary_prints_the_observed_grade_once_per_group() -> None:
    text = atria_campaign._format_failure_diagnostics({
        "exact_instance_failed_cases": _failures(2, observed={
            "variant": "reference", "done": True, "verdict": "FAIL", "score": 0.85,
            "raw_accuracy": 0.86, "failure_mode": "overfit_spatial_layout",
            "failed_checks": ["spatial_layout_invariant"],
            "notes": ["reference memorised the training-resolution layout"],
            "elapsed_seconds": 118.4, "stderr_tail": "line 1: weak model",
        })
    })
    assert "saw: variant=reference done=True verdict=FAIL score=0.85 raw_accuracy=0.86" in text, text
    assert "checks_failing=spatial_layout_invariant" in text, text
    assert "reference memorised the training-resolution layout" in text, text
    # one example for the group, not one per row: the count carries the size
    assert text.count("saw: variant=reference") == 1, text


def test_a_cut_is_announced_rather_than_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {"variant": "reference", "verdict": "FAIL", "score": 0.5,
                "failure_mode": "overfit_spatial_layout", "failed_checks": ["a_check", "b_check"],
                "notes": ["a judge note"], "stderr_tail": "a stderr tail"}
    failures = [
        {"case_id": f"env{index}_architecture=hard_optimizer=hard__seed-{index}",
         "reason": "reference_did_not_grade_as_expected", "observed": observed, "status": "blocked"}
        for index in range(6)
    ]
    # The default limit is generous on purpose, so the boundary is moved to it rather than
    # the summary padded until it happens to overflow.
    monkeypatch.setattr(atria_campaign, "DIAGNOSTIC_CHAR_LIMIT", 400)
    text = atria_campaign._format_failure_diagnostics({"exact_instance_failed_cases": failures})
    assert len(text) <= 400 + 200, len(text)
    assert "cut at 400 chars" in text, text[-300:]
    assert "further line(s)" in text and "instance_oracles.json" in text, text[-300:]
    # the shape survives a cut: the row count is assembled first, so it is always readable
    assert text.startswith(" Provider-free diagnostics:"), text[:40]
    assert "6 blocked exact-instance oracle row(s)" in text, text[:200]

def test_the_default_limit_holds_a_full_group_listing_without_cutting() -> None:
    observed = {"variant": "reference", "verdict": "FAIL", "score": 0.85,
                "failure_mode": "overfit_spatial_layout",
                "failed_checks": ["c" + str(i) for i in range(40)],
                "notes": ["n" * 200] * 3, "stderr_tail": "e" * 400}
    failures = [
        {"case_id": f"env{index}_a=hard_b=hard_c=hard__seed-{index}",
         "reason": "reference_did_not_grade_as_expected", "observed": observed, "status": "blocked"}
        for index in range(60)
    ]
    text = atria_campaign._format_failure_diagnostics({"exact_instance_failed_cases": failures})
    assert "cut at" not in text, "the shipped limit must fit the summary of a 60-row failure set"


def test_the_group_count_and_row_count_survive_a_cut() -> None:
    observed = {"variant": "reference", "verdict": "FAIL", "failed_checks": ["c" + str(i) for i in range(40)],
                "notes": ["n" * 200] * 3, "stderr_tail": "e" * 400}
    failures = [
        {"case_id": f"env{index}_a=hard__seed-0", "reason": "reference_did_not_grade_as_expected",
         "observed": observed, "status": "blocked"}
        for index in range(200)
    ]
    text = atria_campaign._format_failure_diagnostics({"exact_instance_failed_cases": failures})
    assert "200 blocked exact-instance oracle row(s)" in text, text[:200]
    assert "manual_gate_blocked_exclusions" in text or "+188 more of the same" in text, text[-500:]


def test_the_omission_stanza_is_a_suggestion_never_a_self_applied_edit() -> None:
    """The tool prints the stanza for a human; nothing in the codebase appends it.

    Writing it into a profile is how a gate shrinks without anyone deciding to, and it has
    already happened to this project: both pairwise profiles ship 8 glyph rows omitted under
    ``reference_does_not_solve_its_own_instance``. Those are pinned here as a ceiling, so a
    ninth cannot appear without a test failing, and the same class of failure the campaign is
    now blocking on has to be diagnosed rather than added to the list.
    """
    import yaml

    text = atria_campaign._format_failure_diagnostics({"exact_instance_failed_cases": _failures(1)})
    assert "to omit them, add under manual_gate_blocked_exclusions.cases:" in text

    known_classes = set(atria_campaign._BLOCKED_ROW_CALIBRATION_CLASS.values())
    for rel in ("experiments/mercury_pairwise_campaign.yaml",
                "experiments/reasoning_atria_pairwise_campaign.yaml"):
        data = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8")) or {}
        block = data.get("manual_gate_blocked_exclusions") or {}
        cases = block.get("cases") or []
        assert cases, f"{rel}: the omission block exists but holds nothing"
        for entry in cases:
            assert str(entry.get("calibration_class") or "").strip(), (
                f"{rel}: {entry.get('case_id')} is omitted with no stated reason class"
            )
        hand_written = {
            str(entry.get("calibration_class")) for entry in cases
        } - known_classes
        # Three of the shipped entries carry a class the tool never emits - they were written
        # by hand when those rows were dropped. Tolerated, because a human justification is
        # not a gate change, but pinned so new vocabulary cannot be invented to make a
        # blocked row look explained: a class nothing produces can never be matched back to
        # a reason in a log, which is how "reference_fix_already_present_at_symptom_mask_hard"
        # came to sit beside rows this campaign is now blocking on again.
        assert hand_written <= {
            "reference_exists_per_environment_not_per_vector",
            "oracle_assumes_easy_layout",
            "reference_fix_already_present_at_symptom_mask_hard",
        }, hand_written
        glyph_reference = [
            entry for entry in cases
            if str(entry.get("calibration_class")) == "reference_does_not_solve_its_own_instance"
            and str(entry.get("case_id", "")).startswith("glyph__")
        ]
        assert len(glyph_reference) <= 8, (
            f"{rel}: {len(glyph_reference)} glyph reference rows are omitted where 8 are on record; "
            "a blocked reference is a bug to fix, not a row to drop"
        )
        assert block.get("disposition") == "omitted_before_provider_access", (
            f"{rel}: an omission must be recorded as taken before provider access"
        )
