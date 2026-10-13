"""The gate context must track verdict-producing code and nothing else.

`tools/gate_context.py` replaces the old `git rev-parse HEAD` context. Its whole job is a
pair of opposing properties, and both are pinned here:

  * an edit to anything that cannot change a reference value -- docs, a workflow comment, a
    test -- must leave the digest alone, or the campaign re-gates hours of work on every
    commit and never finishes;
  * an edit to an environment template, the gate, or a helper module the gate newly imports
    must move it, or a stale verdict gets trusted as fresh.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import gate_context  # noqa: E402


@pytest.fixture()
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal repository shaped like this one, with the verdict inputs present."""
    for rel in gate_context.EXPLICIT:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n", encoding="utf-8")
    for rel in gate_context.CLOSURE_SEEDS:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "envs" / "glyph").mkdir(parents=True, exist_ok=True)
    (tmp_path / "envs" / "glyph" / "config.yaml").write_text("a: 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("notes\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    monkeypatch.setattr(gate_context, "ROOT", tmp_path)
    return tmp_path


def test_a_verdict_irrelevant_edit_leaves_the_context_untouched(tree: Path) -> None:
    before = gate_context.compute()
    (tree / "README.md").write_text("a handoff note rewrite\n", encoding="utf-8")
    (tree / ".github" / "workflows" / "ci.yml").write_text("name: CI\n\n\n", encoding="utf-8")
    (tree / "handoff").mkdir(exist_ok=True)
    (tree / "handoff" / "notes.md").write_text("new file, new commit\n", encoding="utf-8")
    assert gate_context.compute() == before, (
        "documentation and launcher edits must not invalidate banked gate rows"
    )


@pytest.mark.parametrize(
    "rel",
    ["envs/glyph/config.yaml", "tools/instance_oracle_gate.py", "arena.py", "requirements.txt"],
)
def test_a_verdict_relevant_edit_moves_the_context(tree: Path, rel: str) -> None:
    before = gate_context.compute()
    (tree / rel).write_text("changed: 2\n", encoding="utf-8")
    assert gate_context.compute() != before, f"{rel} decides reference values and must invalidate"


def test_a_newly_imported_helper_is_covered_without_editing_the_list(tree: Path) -> None:
    """The closure, not the list, is what keeps coverage honest as the code moves."""
    before = gate_context.compute()
    (tree / "scoring_core.py").write_text("SCORE = 1\n", encoding="utf-8")
    assert gate_context.compute() == before, "an unimported file is irrelevant"
    seed = tree / "tools" / "run_suite.py"
    seed.write_text("import scoring_core\nX = scoring_core.SCORE\n", encoding="utf-8")
    after = gate_context.compute()
    assert after != before
    (tree / "scoring_core.py").write_text("SCORE = 2\n", encoding="utf-8")
    assert gate_context.compute() != after, (
        "the helper the gate now imports must be inside the context"
    )


def test_a_missing_verdict_input_raises_instead_of_shrinking_the_context(tree: Path) -> None:
    (tree / "arena.py").unlink()
    with pytest.raises(FileNotFoundError, match="verdict-relevant inputs are missing"):
        gate_context.compute()


def test_the_context_is_not_a_git_revision_on_the_real_repository() -> None:
    """Guard against a silent return to `git rev-parse HEAD` in tools/atria_campaign.py."""
    digest = gate_context.compute()
    assert digest.startswith("content-sha256:")
    body = (ROOT / "tools" / "atria_campaign.py").read_text(encoding="utf-8")
    start = body.index("def _gate_context_sha()")
    end = body.index("\ndef ", start + 10)
    function = body[start:end]
    assert '["git", "rev-parse", "HEAD"]' not in function, (
        "the context is the verdict file set; a revision hash in here is the loop back"
    )
    assert "rev-parse" in function, "the docstring must keep explaining what was replaced"
    assert "gate_context" in function, function
    files = gate_context.verdict_relevant_files()
    assert len(files) > 100, "the real repo must cover the whole envs/ tree"
    assert all(path.exists() for path in files)
