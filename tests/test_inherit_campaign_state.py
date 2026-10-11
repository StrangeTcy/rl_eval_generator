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
    report = inherit_state(src, tmp_path / "target", plan=plan, context_sha=HEAD)
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
    report = inherit_state(src, target, plan={case["case_id"]: case_sha256(case)}, context_sha=HEAD)
    assert report["gate_rows_status"] == "refused_gate_context_differs"
    assert report["gate_rows_inherited"] == 0
    assert not (target / GATE_FILE).exists(), "no gate file may be written under a borrowed context"
    assert report["gate_rows_source_context_sha"] == OTHER


def test_an_edited_case_definition_invalidates_only_its_own_row(tmp_path: Path) -> None:
    case = _case("glyph", "easy")
    stale = dict(case)
    stale["difficulty_levels"] = {"a": "medium"}  # plan drifted under the cached row
    src = _source(tmp_path, {case["case_id"]: _row(stale)})
    report = inherit_state(src, tmp_path / "t", plan={case["case_id"]: case_sha256(case)}, context_sha=HEAD)
    assert report["gate_rows_dropped_hash_mismatch"] == 1
    assert report["gate_rows_inherited"] == 0


def test_rows_this_campaign_already_banked_are_never_overwritten(tmp_path: Path) -> None:
    case = _case("glyph", "easy")
    src = _source(tmp_path, {case["case_id"]: {"case_sha256": case_sha256(case), "row": {"status": "failed"}, "attempts": 2}})
    target = tmp_path / "target"
    target.mkdir()
    own = {"case_sha256": case_sha256(case), "row": {"status": "passed", "note": "mine"}, "attempts": 1}
    (target / GATE_FILE).write_text(json.dumps({"gate_context_sha": HEAD, "rows": {case["case_id"]: own}}), encoding="utf-8")
    inherit_state(src, target, plan={case["case_id"]: case_sha256(case)}, context_sha=HEAD)
    rows = json.loads((target / GATE_FILE).read_text(encoding="utf-8"))["rows"]
    assert rows[case["case_id"]]["row"]["note"] == "mine"


def test_the_episode_ledger_and_markers_are_never_inherited(tmp_path: Path) -> None:
    src = _source(tmp_path, {})
    for name in ("suite_checkpoint.json", "campaign_intent.json", "wrapper_failed.json"):
        (src / name).write_text(json.dumps({"results": [{"case_id": "someone_elses_episode"}]}), encoding="utf-8")
    target = tmp_path / "target"
    report = inherit_state(src, target, plan={}, context_sha=HEAD)
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
    report = inherit_state(src, target, plan=plan, context_sha=HEAD, head_sha=HEAD)
    # T1 is judged on the revision the source campaign recorded, not on the gate
    # context: its report measures model-plus-code behaviour across the whole leg.
    assert report["t1_inherited"] is False and "differs_from_head" in report["t1_reason"]
    assert not (target / T1_REPORT).exists()

    target = tmp_path / "t2"
    report = inherit_state(src, target, plan=plan, context_sha=HEAD, head_sha=OTHER,
                           allow_cross_revision_t1=True)
    assert report["t1_inherited"] is True
    assert report["t1_source_ref"] == OTHER, "the borrowed provenance is recorded, not hidden"
    assert json.loads((target / T1_REPORT).read_text(encoding="utf-8"))["calls"] == 72

    (src / CAMPAIGN_REF).write_text(HEAD + "\n", encoding="utf-8")
    target = tmp_path / "t3"
    report = inherit_state(src, target, plan=plan, context_sha=HEAD, head_sha=HEAD)
    assert report["t1_inherited"] is True and report["t1_reason"] == "same_revision"


def test_missing_source_is_not_a_failure(tmp_path: Path) -> None:
    report = inherit_state(tmp_path / "absent", tmp_path / "target", plan={}, context_sha=HEAD)
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


def test_the_carry_keys_on_grading_code_not_on_the_commit(tmp_path: Path) -> None:
    """The property the revision-pinned rule was missing.

    Two campaigns at different commits, with byte-identical verdict-producing code,
    produce the same verdict context, so the row carries. Recording the revision in
    the report is provenance, not a condition -- and before this, a documentation
    commit alone was enough to throw away every banked gate row.
    """
    case = _case("glyph", "easy")
    src = _source(tmp_path, {case["case_id"]: _row(case)})
    plan = {case["case_id"]: case_sha256(case)}
    report = inherit_state(
        src,
        tmp_path / "target",
        plan=plan,
        context_sha=HEAD,
        head_sha=OTHER,
    )
    assert report["gate_rows_status"] == "inherited", report
    assert report["gate_rows_inherited"] == 1
    assert report["context_sha"] == HEAD and report["head_sha"] == OTHER, (
        "the revision is recorded beside the context, never used to judge the carry"
    )


# --------------------------------------------------------------------------- rekey
# Rows banked before the context stopped being a git revision are keyed on a 40-hex
# SHA that no content digest can ever equal. Without a rule they would be dropped
# silently forever; with a bare exception the guard would be laundered. The rule these
# tests pin is the proof version: adopt the rows only when `git diff` over the
# verdict-relevant files between the revision they were produced at and the reading
# checkout comes back empty, and record the proof in the report.
import subprocess  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    (tmp_path / "arena.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("first\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one")
    first = _git(tmp_path, "rev-parse", "HEAD")
    from tools import gate_context

    monkeypatch.setattr(
        gate_context, "verdict_relevant_files", lambda: [tmp_path / "arena.py"]
    )
    return tmp_path, first


def test_identical_grading_code_across_commits_is_proved_not_asserted(repo) -> None:
    from tools.inherit_campaign_state import grading_code_identical

    tmp, first = repo
    (tmp / "notes.md").write_text("a documentation commit\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "docs")
    identical, note = grading_code_identical(first, root=tmp)
    assert identical, note
    assert "byte-identical" in note


def test_grading_code_that_moved_refuses_with_the_file_named(repo) -> None:
    from tools.inherit_campaign_state import grading_code_identical

    tmp, first = repo
    (tmp / "arena.py").write_text("A = 2  # the grader changed\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "grading")
    identical, note = grading_code_identical(first, root=tmp)
    assert not identical
    assert "arena.py" in note, note


def test_an_unreachable_revision_refuses_and_names_the_fetch(repo) -> None:
    from tools.inherit_campaign_state import grading_code_identical

    tmp, _ = repo
    identical, note = grading_code_identical("f" * 40, root=tmp)
    assert not identical
    assert "git fetch" in note, "a refusal the operator cannot act on is a dead end"


def test_a_content_digest_context_is_not_mistaken_for_a_revision(repo) -> None:
    from tools.inherit_campaign_state import grading_code_identical

    tmp, _ = repo
    identical, note = grading_code_identical("content-sha256:" + "a" * 64, root=tmp)
    assert not identical and "not a revision" in note


def test_legacy_rows_carry_once_the_proof_holds(tmp_path: Path, repo) -> None:
    from tools.inherit_campaign_state import grading_code_identical  # noqa: F401

    tmp, first = repo
    (tmp / "notes.md").write_text("docs only\n", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "docs")
    case = _case("glyph", "easy")
    src = _source(tmp_path / "legacy", {case["case_id"]: _row(case)}, context=first)
    target = tmp_path / "target"
    report = inherit_state(
        src,
        target,
        plan={case["case_id"]: case_sha256(case)},
        context_sha="content-sha256:" + "b" * 64,
        grading_diff_root=tmp,
    )
    assert report["gate_rows_status"] == "inherited", report
    assert report["gate_rows_rekeyed_from"] == first
    assert "byte-identical" in report["gate_rows_rekey_note"]
    written = json.loads((target / GATE_FILE).read_text(encoding="utf-8"))
    assert written["gate_context_sha"] == "content-sha256:" + "b" * 64, (
        "the adopted rows are re-keyed to the identity the reader will check, not hidden"
    )


def test_legacy_rows_still_refuse_when_the_grader_changed(tmp_path: Path, repo) -> None:
    case = _case("glyph", "easy")
    src = _source(tmp_path / "legacy", {case["case_id"]: _row(case)}, context="c" * 40)
    report = inherit_state(
        src,
        tmp_path / "target",
        plan={case["case_id"]: case_sha256(case)},
        context_sha="content-sha256:" + "b" * 64,
        grading_diff_root=repo[0],
    )
    assert report["gate_rows_status"] == "refused_gate_context_differs"
    assert "fetch" in report["gate_rows_refusal_note"], report["gate_rows_refusal_note"]


def test_a_checkout_without_the_content_digest_still_keys_on_the_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The launcher runs this tool against the campaign's *pinned* checkout.

    A pinned ref that predates tools/gate_context.py has a run_suite which still keys
    rows on `git rev-parse HEAD`, so a hard import here would crash the inherit step and
    kill the leg over a bookkeeping detail. The tool follows the reader's convention and
    says so out loud.
    """
    import json as _json

    import tools.inherit_campaign_state as mod

    case = _case("glyph", "easy")
    src = _source(tmp_path, {case["case_id"]: _row(case)}, context=HEAD)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        _json.dumps({"cases": [{"case_id": case["case_id"], **case}]}), encoding="utf-8"
    )
    monkeypatch.setattr(mod, "gate_context", None)
    monkeypatch.setattr(mod, "current_head", lambda root=ROOT: HEAD)
    monkeypatch.setattr(
        sys, "argv",
        ["inherit", "--from", str(src), "--to", str(tmp_path / "target"),
         "--manifest", str(manifest)],
    )
    assert mod.main() == 0, "the step must not fail the leg over a missing module"
    captured = capsys.readouterr()
    assert "keying gate rows on the revision" in captured.out, captured.out
    written = json.loads((tmp_path / "target" / GATE_FILE).read_text(encoding="utf-8"))
    assert written["gate_context_sha"] == HEAD
    assert list(written["rows"]) == [case["case_id"]]
