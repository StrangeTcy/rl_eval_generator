"""Carrying exact-instance gate rows across a matrix-mode change.

Strength-2 does not subsume strength-1 case for case, so a richer campaign cannot
resume the earlier run - but a *gate row* is keyed on the case's own content hash
under the current revision, not on which plan asked for it. These tests pin both
halves: what may carry, and the refusal that keeps it honest.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.inherit_campaign_state import (  # noqa: E402
    CAMPAIGN_REF,
    GATE_FILE,
    T1_REPORT,
    case_sha256,
    inherit_state,
)

HEAD = "a" * 40
OTHER = "b" * 40


def _case(env: str, vector: str) -> dict:
    return {
        "case_id": f"{env}__{vector}__seed-0",
        "environment": env,
        "difficulty": vector,
        "difficulty_levels": {"a": vector},
        "seed": 0,
    }


def _row(case: dict, *, status: str = "passed") -> dict:
    return {"case_sha256": case_sha256(case), "row": {"status": status, "note": "gated"}, "attempts": 1}


def _source(tmp: Path, rows: dict, *, context: str = HEAD) -> Path:
    src = tmp / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / GATE_FILE).write_text(
        json.dumps({"gate_context_sha": context, "rows": rows}, indent=2), encoding="utf-8"
    )
    return src


def test_rows_in_the_new_plan_carry_at_the_same_revision(tmp_path: Path) -> None:
    kept = _case("glyph", "easy")
    dropped = _case("moco", "hard")
    src = _source(tmp_path, {kept["case_id"]: _row(kept), dropped["case_id"]: _row(dropped)})
    plan = {kept["case_id"]: case_sha256(kept)}
    report = inherit_state(src, tmp_path / "target", plan=plan, head_sha=HEAD)
    assert report["gate_rows_status"] == "inherited"
    assert report["gate_rows_inherited"] == 1
    assert report["gate_rows_dropped_not_in_plan"] == 1, "a case this plan never bills is not carried"
    written = json.loads((tmp_path / "target" / GATE_FILE).read_text(encoding="utf-8"))
    assert written["gate_context_sha"] == HEAD
    assert list(written["rows"]) == [kept["case_id"]]


def test_a_different_revision_refuses_the_carry_and_says_so(tmp_path: Path) -> None:
    """The refusal is the point: a row's verdict is a claim about the code that
    graded it, so crossing revisions must re-gate rather than be laundered."""
    case = _case("glyph", "easy")
    src = _source(tmp_path, {case["case_id"]: _row(case)}, context=OTHER)
    target = tmp_path / "target"
    report = inherit_state(src, target, plan={case["case_id"]: case_sha256(case)}, head_sha=HEAD)
    assert report["gate_rows_status"] == "refused_gate_context_differs"
    assert report["gate_rows_inherited"] == 0
    assert not (target / GATE_FILE).exists(), "no gate file may be written under a borrowed context"
    assert report["gate_rows_source_context_sha"] == OTHER


def test_an_edited_case_definition_invalidates_only_its_own_row(tmp_path: Path) -> None:
    case = _case("glyph", "easy")
    stale = dict(case)
    stale["difficulty_levels"] = {"a": "medium"}  # plan drifted under the cached row
    src = _source(tmp_path, {case["case_id"]: _row(stale)})
    report = inherit_state(src, tmp_path / "t", plan={case["case_id"]: case_sha256(case)}, head_sha=HEAD)
    assert report["gate_rows_dropped_hash_mismatch"] == 1
    assert report["gate_rows_inherited"] == 0


def test_rows_this_campaign_already_banked_are_never_overwritten(tmp_path: Path) -> None:
    case = _case("glyph", "easy")
    src = _source(tmp_path, {case["case_id"]: {"case_sha256": case_sha256(case), "row": {"status": "failed"}, "attempts": 2}})
    target = tmp_path / "target"
    target.mkdir()
    own = {"case_sha256": case_sha256(case), "row": {"status": "passed", "note": "mine"}, "attempts": 1}
    (target / GATE_FILE).write_text(json.dumps({"gate_context_sha": HEAD, "rows": {case["case_id"]: own}}), encoding="utf-8")
    inherit_state(src, target, plan={case["case_id"]: case_sha256(case)}, head_sha=HEAD)
    rows = json.loads((target / GATE_FILE).read_text(encoding="utf-8"))["rows"]
    assert rows[case["case_id"]]["row"]["note"] == "mine"


def test_the_episode_ledger_and_markers_are_never_inherited(tmp_path: Path) -> None:
    src = _source(tmp_path, {})
    for name in ("suite_checkpoint.json", "campaign_intent.json", "wrapper_failed.json"):
        (src / name).write_text(json.dumps({"results": [{"case_id": "someone_elses_episode"}]}), encoding="utf-8")
    target = tmp_path / "target"
    report = inherit_state(src, target, plan={}, head_sha=HEAD)
    assert report["gate_rows_status"] == "source_has_no_rows"
    for name in ("suite_checkpoint.json", "campaign_intent.json", "wrapper_failed.json"):
        assert not (target / name).exists(), f"{name} is campaign-scoped"


def test_t1_follows_the_same_revision_rule_unless_told_otherwise(tmp_path: Path) -> None:
    case = _case("glyph", "easy")
    src = _source(tmp_path, {case["case_id"]: _row(case)})
    (src / T1_REPORT).write_text(json.dumps({"status": "complete", "calls": 72}), encoding="utf-8")
    (src / CAMPAIGN_REF).write_text(OTHER + "\n", encoding="utf-8")
    plan = {case["case_id"]: case_sha256(case)}

    target = tmp_path / "t1"
    report = inherit_state(src, target, plan=plan, head_sha=HEAD)
    assert report["t1_inherited"] is False and "differs_from_head" in report["t1_reason"]
    assert not (target / T1_REPORT).exists()

    target = tmp_path / "t2"
    report = inherit_state(src, target, plan=plan, head_sha=HEAD, allow_cross_revision_t1=True)
    assert report["t1_inherited"] is True
    assert report["t1_source_ref"] == OTHER, "the borrowed provenance is recorded, not hidden"
    assert json.loads((target / T1_REPORT).read_text(encoding="utf-8"))["calls"] == 72

    (src / CAMPAIGN_REF).write_text(HEAD + "\n", encoding="utf-8")
    target = tmp_path / "t3"
    report = inherit_state(src, target, plan=plan, head_sha=HEAD)
    assert report["t1_inherited"] is True and report["t1_reason"] == "same_revision"


def test_missing_source_is_not_a_failure(tmp_path: Path) -> None:
    report = inherit_state(tmp_path / "absent", tmp_path / "target", plan={}, head_sha=HEAD)
    assert report["gate_rows_status"] == "no_source_file"
    assert report["t1_reason"] == "no_source_report"


def test_plan_comes_from_the_same_builder_the_campaign_uses(tmp_path: Path) -> None:
    from tools import atria_campaign

    profile = ROOT / "experiments/mercury_pairwise_campaign.yaml"
    manifest = atria_campaign.build_manifest(
        root=ROOT, matrix="pairwise", seeds=[0], expand_interventions=True
    )
    written = tmp_path / "pilot_manifest.json"
    written.write_text(json.dumps(manifest), encoding="utf-8")
    from tools.inherit_campaign_state import plan_cases

    via_manifest = plan_cases(profile_path=None, manifest_path=written)
    via_profile = plan_cases(profile_path=profile, manifest_path=None)
    assert via_manifest == via_profile, "the inherit step must judge the plan the campaign will bill"
    assert len(via_profile) == 496


@pytest.mark.parametrize("slug", ["mercury", "reasoning-atria"])
def test_pairwise_workflows_inherit_from_the_covering_campaign_only(slug: Path) -> None:
    text = (ROOT / f"handoff/{slug}-pairwise-campaign.yml").read_text()
    steps = [line.strip() for line in text.splitlines() if line.strip().startswith("- name:")]
    names = [s[len("- name:"):].strip() for s in steps]
    assert "Inherit exact-instance gate rows from the covering campaign" in names
    paid = names.index("Run T1 and pairwise campaign with live Issue status")
    assert names.index("Inherit exact-instance gate rows from the covering campaign") == paid - 1, (
        "inheritance must land after the state restore and before anything is billed"
    )
    assert "-covering-campaign.yml/runs" in text, "it must read the covering workflow's runs"
    assert f"{slug}-covering-state-" in text, "and its state artifact prefix, not this campaign's"
    assert "test -f tools/inherit_campaign_state.py" in text
    assert "this campaign already has gate rows of its own" in text
    block = text[text.index("Inherit exact-instance gate rows"):paid_start(text)]
    assert "|| true" in block and "|| echo" in block, "inheritance is an optimization: it must never fail a tick"


def paid_start(text: str) -> int:
    return text.index("Run T1 and pairwise campaign with live Issue status")
