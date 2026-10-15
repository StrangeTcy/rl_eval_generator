"""A ceiling the operator raised is a budget decision, not a changed measurement.

Before this, stopping on `max_tokens_total` was a dead end with no exit: the value lives in
`experiments/*.yaml`, the running campaign is pinned to the commit that read it, so editing
the profile could not reach it, and a fresh dispatch to pick the edit up discarded the state
the campaign had accumulated. `run_suite` also treats the ceilings as immutable checkpoint
metadata, which is right for a *silent* change and wrong for an authorised one.

These tests pin both halves of the narrow opening: a raise that names an authoriser is
recorded and lets the tick resume, and everything else - no authorisation, an equal value,
a reduction, a measurement field - still refuses.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_suite  # noqa: E402
from tools.atria_campaign import _apply_limit_overrides  # noqa: E402
from tools.campaign_supervisor import decide_tick  # noqa: E402

REF = "f" * 40
CEILING = 136_000_000


def _old_timestamp() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def _paused_state(tmp_path: Path, *, reason: str = "max_tokens_total", ceiling: int = CEILING) -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    (tmp_path / "campaign_intent.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "mercury",
                "execution_mode": "paid",
                "case_manifest_sha256": "a" * 64,
                "gate_context_sha": REF,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": True,
                "pause_reason": reason,
                "updated_at": _old_timestamp(),
                "manifest_case_count": 1,
                "results": [],
                "run": {
                    "manifest_commit": REF,
                    "provider": "mercury",
                    "execution_state": "paid",
                    "max_tokens_total": ceiling,
                    "max_api_calls": 21200,
                    "max_http_attempts": 4000,
                },
            }
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ supervisor
def test_a_spent_ceiling_stops_the_cron_loop_by_default(tmp_path: Path) -> None:
    _paused_state(tmp_path)
    decision = decide_tick(tmp_path, expected_provider="mercury")
    assert decision["mode"] == "none"
    assert "never raises ceilings" in decision["reason"]
    assert "dispatch max_tokens_total=" in decision["reason"], (
        "the refusal must name the one action that unblocks it"
    )


@pytest.mark.parametrize("override", [None, {}, {"max_tokens_total": CEILING}, {"max_tokens_total": 5}])
def test_an_override_that_is_not_a_raise_does_not_lift_the_pause(tmp_path: Path, override) -> None:
    """Equal or lower is no new budget, so there is nothing to resume into."""
    _paused_state(tmp_path)
    decision = decide_tick(tmp_path, expected_provider="mercury", limits_override=override)
    assert decision["mode"] == "none", override


def test_a_raised_ceiling_resumes_and_says_so(tmp_path: Path) -> None:
    _paused_state(tmp_path)
    decision = decide_tick(
        tmp_path,
        expected_provider="mercury",
        limits_override={"max_tokens_total": CEILING + 50_000_000},
    )
    assert decision["mode"] == "resume", decision
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == REF
    assert "raised by dispatcher" in decision["reason"], decision["reason"]


def test_the_raise_is_read_from_strings_because_actions_inputs_are_strings(tmp_path: Path) -> None:
    _paused_state(tmp_path)
    decision = decide_tick(
        tmp_path,
        expected_provider="mercury",
        limits_override=["max_tokens_total=%d" % (CEILING + 1)],
    )
    assert decision["mode"] == "resume", decision


def test_a_pause_with_no_recorded_ceiling_is_not_guessed_at(tmp_path: Path) -> None:
    """Refusing beats resuming on an assumption about how much budget is left."""
    _paused_state(tmp_path, ceiling=0)
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps(
            {
                "paused": True,
                "pause_reason": "max_tokens_total",
                "updated_at": _old_timestamp(),
                "manifest_case_count": 1,
                "results": [],
                "run": {"manifest_commit": REF, "provider": "mercury"},
            }
        ),
        encoding="utf-8",
    )
    decision = decide_tick(
        tmp_path, expected_provider="mercury", limits_override={"max_tokens_total": 999_999_999}
    )
    assert decision["mode"] == "none"


def test_an_unrelated_pause_reason_is_untouched(tmp_path: Path) -> None:
    _paused_state(tmp_path, reason="floor_effect")
    decision = decide_tick(
        tmp_path, expected_provider="mercury", limits_override={"max_tokens_total": 10 ** 12}
    )
    assert decision["mode"] == "none", (
        "a money override must not become a general-purpose resume override"
    )


# ------------------------------------------------------------------ checkpoint
def _checkpoint_file(tmp_path: Path, metadata: dict) -> Path:
    path = tmp_path / "suite_checkpoint.json"
    path.write_text(json.dumps({"run": metadata, "results": [], "manifest_case_count": 1}), encoding="utf-8")
    return path


def _load(tmp_path: Path, previous: dict, current: dict, *, authorized_by=None, rebase=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = _checkpoint_file(tmp_path, previous)
    manifest = {"case_count": 1, "cases": []}
    return run_suite._load_checkpoint(
        path,
        manifest=manifest,
        metadata=current,
        ceiling_authorization=authorized_by,
        allow_manifest_commit_rebase=rebase,
    )


def test_a_rebase_moves_the_commit_and_records_the_move_beside_the_rows(tmp_path: Path) -> None:
    """`manifest_commit` is the one field a manual rebase may change, and only with the flag set.

    Measured cost of it not being movable: the Mercury ledger was written under 0ddcd39, a rebase
    re-pinned the intent to a newer commit, and every leg after that died ~2.5 minutes in on
    `checkpoint metadata mismatch for manifest_commit` (runs 24 and 25, 2026-10-13) - while the only
    other way onto new code, a fresh dispatch, discards the 190 banked episodes and re-bills T1.
    """
    previous = {"provider": "mercury", "manifest_commit": "0ddcd39"}
    current = {**previous, "manifest_commit": "bf8ca43"}
    with pytest.raises(ValueError, match="checkpoint metadata mismatch for manifest_commit"):
        _load(tmp_path / "strict", previous, current)

    checkpoint = _load(tmp_path / "rebase", previous, current, rebase=True)
    assert checkpoint is not None
    moves = checkpoint["manifest_commit_moves"]
    assert len(moves) == 1, moves
    assert moves[0]["from"] == "0ddcd39"
    assert moves[0]["to"] == "bf8ca43"
    assert moves[0]["authorized_by"] == "rebase-intent"
    assert checkpoint["run"]["manifest_commit"] == "bf8ca43"

    # Every other field still refuses, rebase or not: the waiver is about where the code came from,
    # never about what the run is allowed to be.
    for field, value in (("provider", "atria"), ("model", "other-1"), ("api_base", "https://x/v1"),
                         ("max_steps", 99), ("secrets", "extra"), ("wire_api", "responses")):
        with pytest.raises(ValueError, match=f"checkpoint metadata mismatch for {field}"):
            _load(tmp_path / f"refuse-{field}", previous, {**previous, field: value}, rebase=True)

    # A second rebase appends rather than overwrites, so the lineage's whole code history stays readable.
    moved_file = tmp_path / "rebase" / "suite_checkpoint.json"
    moved = json.loads(moved_file.read_text(encoding="utf-8")) if moved_file.is_file() else None
    carried = {
        "run": {**previous, "manifest_commit": "bf8ca43"},
        "manifest_commit_moves": [{"from": "0ddcd39", "to": "bf8ca43", "authorized_by": "rebase-intent"}],
        "results": [],
        "manifest_case_count": 1,
    }
    twice_dir = tmp_path / "twice"
    twice_dir.mkdir(parents=True, exist_ok=True)
    (twice_dir / "suite_checkpoint.json").write_text(json.dumps(carried), encoding="utf-8")
    again = run_suite._load_checkpoint(
        twice_dir / "suite_checkpoint.json",
        manifest={"case_count": 1, "cases": []},
        metadata={**previous, "manifest_commit": "c0ffee1"},
        allow_manifest_commit_rebase=True,
    )
    assert again["run"]["manifest_commit"] == "c0ffee1"
    assert [move["from"] for move in again["manifest_commit_moves"]] == ["0ddcd39", "bf8ca43"]


def test_a_ceiling_raise_without_authorisation_still_refuses(tmp_path: Path) -> None:
    previous = {"provider": "mercury", "max_tokens_total": 100}
    with pytest.raises(ValueError, match="needs the operator's explicit authorisation"):
        _load(tmp_path, previous, {**previous, "max_tokens_total": 200})


def test_an_authorised_raise_is_recorded_against_the_rows_it_buys(tmp_path: Path) -> None:
    previous = {"provider": "mercury", "max_tokens_total": 100, "max_api_calls": 10}
    checkpoint = _load(
        tmp_path,
        previous,
        {**previous, "max_tokens_total": 200, "max_api_calls": 40},
        authorized_by="operator-handle",
    )
    entries = checkpoint["ceiling_raises"]
    assert {e["field"] for e in entries} == {"max_tokens_total", "max_api_calls"}
    assert all(e["authorized_by"] == "operator-handle" and e["at"] for e in entries)
    assert {e["from"] for e in entries} == {100, 10} and {e["to"] for e in entries} == {200, 40}


def test_a_second_authorised_raise_appends_rather_than_overwrites(tmp_path: Path) -> None:
    previous = {"provider": "mercury", "max_tokens_total": 100}
    checkpoint = _load(tmp_path, previous, {**previous, "max_tokens_total": 200}, authorized_by="op")
    assert len(checkpoint["ceiling_raises"]) == 1
    (tmp_path / "suite_checkpoint.json").write_text(
        json.dumps(
            {
                "run": {**previous, "max_tokens_total": 200},
                "ceiling_raises": checkpoint["ceiling_raises"],
                "manifest_case_count": 1,
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    again = run_suite._load_checkpoint(
        tmp_path / "suite_checkpoint.json",
        manifest={"case_count": 1, "cases": []},
        metadata={**previous, "max_tokens_total": 300},
        ceiling_authorization="op",
    )
    assert [e["to"] for e in again["ceiling_raises"]] == [200, 300], (
        "the whole spend history of a campaign has to be readable from one file"
    )


def test_a_reduction_is_refused_however_it_is_authorised(tmp_path: Path) -> None:
    previous = {"provider": "mercury", "max_tokens_total": 200}
    with pytest.raises(ValueError, match="refuses to lower"):
        _load(tmp_path, previous, {**previous, "max_tokens_total": 100}, authorized_by="op")


def test_a_measurement_field_still_refuses_under_an_authorisation(tmp_path: Path) -> None:
    """The authorisation is about money, never about what is being measured."""
    previous = {"provider": "mercury", "model": "m0", "max_tokens_total": 100}
    with pytest.raises(ValueError, match="checkpoint metadata mismatch for model"):
        _load(tmp_path, previous, {**previous, "model": "m1"}, authorized_by="op")


# ------------------------------------------------------------------ CLI
def _args(**kwargs) -> argparse.Namespace:
    base = {"limit_overrides": [], "ceiling_authorization": None}
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_cli_accepts_only_the_ceiling_keys() -> None:
    parser = argparse.ArgumentParser()
    profile = {"limits": {"max_tokens_total": 100}}
    assert _apply_limit_overrides(profile, _args(limit_overrides=["max_tokens_total=250"]), parser) == {
        "max_tokens_total": 250
    }
    with pytest.raises(SystemExit):
        _apply_limit_overrides(profile, _args(limit_overrides=["model=m1"]), parser)
    with pytest.raises(SystemExit):
        _apply_limit_overrides(profile, _args(limit_overrides=["max_api_calls=soon"]), parser)
    with pytest.raises(SystemExit):
        _apply_limit_overrides(profile, _args(limit_overrides=["max_api_calls=0"]), parser)
    assert profile["limits"] == {"max_tokens_total": 100}, (
        "the profile the campaign is pinned to is never rewritten in place"
    )

def test_a_refusal_names_every_difference_not_just_the_first(tmp_path: Path) -> None:
    """Three Mercury legs bought one field each; that price is the reason this exists.

    Runs 22, 24 and 25 each died ~2.5 minutes into `_load_checkpoint`, each printing only the first
    mismatching field, so learning that a carried artifact contradicts itself took three dispatches.
    Neither side can download the state artifact to check, so the leg has to answer completely.
    """
    previous = {"provider": "mercury", "model": "mercury-2.5", "manifest_commit": "0ddcd39"}
    current = {"provider": "atria", "model": "other-1", "manifest_commit": "5cb4205"}
    with pytest.raises(ValueError) as caught:
        _load(tmp_path, previous, current)
    text = str(caught.value)
    assert "checkpoint metadata mismatch for manifest_commit, provider, model" in text, text
    assert "'0ddcd39' != '5cb4205'" in text, text
    assert "carried by the ledger:" in text and "computed by this leg:" in text, text
    # The printed blocks are diagnostics, so they must not be able to carry a credential. No field
    # in the immutable set holds a secret today; this is the guard for the day one is added.
    printable = run_suite._without_secrets(
        {"api_key": "sk-live-secret", "bearer": "tok", "api_base": "https://api/x/v1", "api_key_env": "MERCURY_API_KEY"}
    )
    assert printable["api_key"] == "<redacted>" and printable["bearer"] == "<redacted>", printable
    # The match is on the key name, so `api_key_env` - an environment variable name, not a value -
    # is hidden too. Losing that one name from a diagnostic is the cheaper side of the mistake.
    assert printable["api_base"] == "https://api/x/v1" and printable["api_key_env"] == "<redacted>"

# The pair from the wedged Mercury lineage was `0ddcd396b45f46b9fbbba7d477b34221a3724ef2` (the ledger's
# own commit) against `5cb4205ae3f69c72809e4834e52006b3406fb3a7` (the stamp the re-pinning leg wrote into
# the manifest), and `git merge-base --is-ancestor` says the first is reachable from the second, which is
# what made that a fast-forward of one lineage rather than a fork. Those two names are not used here any
# more: they were the checkout's business to remember, and CI checks this repository out with
# `fetch-depth: 1`, where it can recall neither - so the assertions below build the same shape of history
# themselves.


def _two_commit_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A throwaway git repository with two real commits: (root, parent, child).

    Ancestry is what these assertions are about, so they make their own history instead of naming two
    commits of this branch. The old form - `0ddcd39` and `5cb4205`, hard-coded - was true of a full clone
    and false of the `fetch-depth: 1` checkout CI uses, where git cannot see either object and the
    fail-closed answer is "not an ancestor": the suite measured the machine, and was red in CI for it.
    """
    import subprocess

    repo = tmp_path / "gitrepo"
    repo.mkdir(parents=True, exist_ok=True)

    def git(*args: str) -> str:
        done = subprocess.run(("git", "-C", str(repo)) + args, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    git("init", "-q")
    git("config", "user.email", "campaign@example.invalid")
    git("config", "user.name", "campaign")
    (repo / "ledger").write_text("first\n", encoding="utf-8")
    git("add", "ledger")
    git("commit", "-qm", "one")
    parent = git("rev-parse", "HEAD")
    (repo / "ledger").write_text("second\n", encoding="utf-8")
    git("add", "ledger")
    git("commit", "-qm", "two")
    return repo, parent, git("rev-parse", "HEAD")


def test_a_hand_started_descendant_carries_the_ledger_without_being_asked(tmp_path: Path, monkeypatch) -> None:
    """Ancestor + manual dispatch is its own authority; the flag is the fallback, not the only door.

    Run 28 (38335486606) reached the controller without `--rebase-intent`, refused this exact pair, and
    wrote a fourth marker. A dispatch that names a ref but forgets an acknowledgement cannot be told
    apart from one that named the wrong ref, and that ambiguity is what kept the loop turning.
    """
    repo, parent, child = _two_commit_repo(tmp_path)
    monkeypatch.setattr(run_suite, "_REPO_ROOT", repo)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    previous = {"provider": "mercury", "manifest_commit": parent}
    current = {**previous, "manifest_commit": child}

    checkpoint = _load(tmp_path / "ancestor", previous, current)
    moves = checkpoint["manifest_commit_moves"]
    assert moves[0]["authorized_by"] == "manual-ancestry", moves
    assert checkpoint["run"]["manifest_commit"] == child

    # Backwards is not a fast-forward, so it is still a refusal...
    with pytest.raises(ValueError, match="checkpoint metadata mismatch for manifest_commit"):
        _load(tmp_path / "rewind", current, previous)

    # ...and so is a scheduled tick, which may not re-pin a lineage no matter how tidy its history is.
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    with pytest.raises(ValueError, match="checkpoint metadata mismatch for manifest_commit"):
        _load(tmp_path / "cron", previous, current)

    # An object the checkout cannot see - a sibling branch, a rewritten lineage, prose - never authorizes.
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    for bogus in ("not-a-sha", "0" * 40, "z" * 8):
        with pytest.raises(ValueError, match="checkpoint metadata mismatch for manifest_commit"):
            _load(tmp_path / f"bogus-{bogus}", previous, {**previous, "manifest_commit": bogus})

    # A 7-character abbreviation is a commit reference, and git resolves it the same way: the check is
    # ancestry, not string length. Asserted so nobody "hardens" this into a format test.
    short = _load(tmp_path / "abbrev", previous, {**previous, "manifest_commit": child[:7]})
    assert short["run"]["manifest_commit"] == child[:7]

