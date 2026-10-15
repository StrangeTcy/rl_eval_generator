from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.campaign_supervisor import decide_tick


REF = "f" * 40


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _state(
    tmp_path: Path, *, execution_mode: str = "paid", campaign_ref: str = REF,
    provider: str = "atria",
) -> None:
    (tmp_path / "campaign_ref.txt").write_text(campaign_ref + "\n", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_intent.json",
        {
            "schema_version": 1,
            "provider": provider,
            "execution_mode": execution_mode,
            "case_manifest_sha256": "a" * 64,
            "gate_context_sha": REF,
        },
    )


def _old_timestamp() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def test_setup_bootstrap_state_resumes_after_pre_controller_failure(tmp_path: Path) -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_bootstrap.json",
        {"provider": "atria", "execution_mode": "paid"},
    )

    decision = decide_tick(tmp_path)

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == REF


def test_gate_wall_pause_resumes_without_a_suite_checkpoint(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    (tmp_path / "instance_oracles_partial.json").write_text("{}", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_report.json",
        {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True},
    )

    assert decide_tick(tmp_path) == {
        "mode": "resume",
        "execution_mode": "paid",
        "ref": REF,
        "reason": "resuming provider-free gate after an interrupted partial row",
    }


def test_gate_only_intent_resumes_the_same_provider_free_mode(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="gates_only")
    (tmp_path / "instance_oracles_partial.json").write_text("{}", encoding="utf-8")
    _write_json(
        tmp_path / "campaign_report.json",
        {"status": "paused", "pause_reason": "max_wall_seconds", "resumable": True},
    )

    decision = decide_tick(tmp_path)

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "gates_only"
    assert decision["ref"] == REF


def test_episode_wall_pause_resumes_only_the_pinned_intended_mode(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "max_wall_seconds",
            "updated_at": _old_timestamp(),
            "run": {"manifest_commit": REF},
        },
    )

    decision = decide_tick(tmp_path)

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == REF
    assert decision["reason"] == "resuming after max_wall_seconds"


def test_bounded_container_failure_pause_resumes_but_exhaustion_does_not(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "infrastructure_error",
            "updated_at": _old_timestamp(),
            "infrastructure_retries": {"case-10": 1},
            "run": {"manifest_commit": REF},
        },
    )
    assert decide_tick(tmp_path)["mode"] == "resume"

    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "infrastructure_error_retries_exhausted",
            "updated_at": _old_timestamp(),
            "infrastructure_retries": {"case-10": 4},
            "run": {"manifest_commit": REF},
        },
    )
    assert decide_tick(tmp_path)["mode"] == "none"


def test_interrupted_active_episode_worker_resumes_without_manual_restart(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": False,
            "results": [{"case_id": "case-0", "status": "scored"}],
            "run": {
                "manifest_commit": REF,
                "execution_state": "active",
                "active_case_id": "case-1",
            },
        },
    )

    assert decide_tick(tmp_path) == {
        "mode": "resume",
        "execution_mode": "paid",
        "ref": REF,
        "reason": "resuming after an interrupted active worker",
    }


def test_completed_or_terminal_state_never_restarts_on_schedule(tmp_path: Path) -> None:
    _state(tmp_path)
    _write_json(tmp_path / "campaign_report.json", {"status": "gate_passed"})
    assert decide_tick(tmp_path)["mode"] == "none"

    _write_json(tmp_path / "campaign_report.json", {"status": "paused", "pause_reason": "max_wall_seconds"})
    _write_json(tmp_path / "wrapper_failed.json", {"pause_reason": "generation_preflight_failed"})
    assert decide_tick(tmp_path)["mode"] == "none"


def test_supervisor_can_validate_a_provider_specific_state(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    assert decide_tick(tmp_path, expected_provider="atria")["mode"] == "resume"
    assert decide_tick(tmp_path, expected_provider="mercury") == {
        "mode": "none",
        "reason": "state artifact intent provider does not match expected target 'mercury'",
    }


def test_interrupted_non_checkpointed_t1_is_an_operator_stop(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid", provider="mercury")
    (tmp_path / "t1_started.json").write_text('{"phase":"started"}', encoding="utf-8")

    decision = decide_tick(tmp_path, expected_provider="mercury")

    assert decision["mode"] == "none"
    assert "no automatic provider-call replay" in decision["reason"]


def test_completed_t1_report_allows_campaign_resume(tmp_path: Path) -> None:
    _state(tmp_path, execution_mode="paid")
    (tmp_path / "t1_started.json").write_text('{"phase":"started"}', encoding="utf-8")
    (tmp_path / "t1_same_fact_presentation.json").write_text("{}", encoding="utf-8")

    decision = decide_tick(tmp_path, expected_provider="atria")

    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"


def test_missing_state_fails_closed_and_branch_name_dispatch_resumes_pinned(tmp_path: Path) -> None:
    (tmp_path / "campaign_ref.txt").write_text(REF + "\n", encoding="utf-8")
    assert decide_tick(tmp_path)["mode"] == "none"

    # campaign_ref.txt holds the dispatched ref STRING (a branch name, or the
    # default "main"), while the checkpoint records the commit SHA the
    # controller executed. A mismatch must resume pinned to the checkpoint's
    # commit — the exact code that produced the state — instead of refusing:
    # a strict string comparison permanently blocks every branch-name
    # dispatch, and the advertised cron continuation never runs.
    _state(tmp_path, campaign_ref="arena/01a0ed2f-rl-eval-generator")
    _write_json(
        tmp_path / "suite_checkpoint.json",
        {
            "paused": True,
            "pause_reason": "max_wall_seconds",
            "updated_at": _old_timestamp(),
            "run": {"manifest_commit": REF},
        },
    )
    decision = decide_tick(tmp_path)
    assert decision["mode"] == "resume"
    assert decision["execution_mode"] == "paid"
    assert decision["ref"] == REF
    assert "pinned to checkpoint commit" in decision["reason"]


LEDGER = "0ddcd396b45f46b9fbbba7d477b34221a3724ef2"
STAMPED = "5cb4205ae3f69c72809e4834e52006b3406fb3a7"
CONTRACT_DETAIL = (
    "checkpoint metadata mismatch for manifest_commit: "
    f"'{LEDGER}' != '{STAMPED}'"
)


def _gated(tmp_path: Path, *, name: str, detail: str, ledger: str, stamped: str | None) -> str:
    """Stage a state whose only obstacle is a recorded terminal marker, and return the reason.

    Each call gets its own directory: the verdict reads every staged file it can find, and one test
    asserting several artifacts would otherwise be reading the previous assertion's manifest.
    """
    state = tmp_path / name
    state.mkdir(parents=True, exist_ok=True)
    _state(state, provider="mercury")
    _write_json(state / "wrapper_failed.json", {"pause_reason": "wrapper_exception", "detail": detail})
    _write_json(state / "suite_checkpoint.json", {"run": {"manifest_commit": ledger}, "results": []})
    if stamped is not None:
        _write_json(state / "suite_manifest.json", {"repository": {"commit": stamped}})
    return decide_tick(state, expected_provider="mercury")["reason"]


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


def test_an_operator_gate_its_code_cannot_reproduce_says_so(tmp_path: Path) -> None:
    """Runs 27 and 29 died on a marker whose cause was a stamp mismatch, and the reason line said nothing
    about whether that mismatch could still happen. It is computable from the staged files, so it is now
    computed here - the answer belongs on the run page, not in somebody's recollection of the code."""
    reason = _gated(tmp_path, name="agreed", detail=CONTRACT_DETAIL, ledger=STAMPED, stamped=STAMPED)
    assert "cannot recur here" in reason, reason
    assert "`clear_wrapper_stop` alone is sufficient" in reason, reason
    assert reason.startswith("operator stop: wrapper_exception")  # the refusal itself never softens


def test_a_self_contradictory_artifact_is_described_by_its_ancestry(tmp_path: Path, monkeypatch) -> None:
    repo, parent, child = _two_commit_repo(tmp_path)
    from tools import campaign_supervisor

    monkeypatch.setattr(campaign_supervisor, "GIT_ROOT", str(repo))

    # A parent commit in a checkpoint and a child commit in the manifest is a fast-forward, measured with
    # the same git command the helper runs, so a leg started on that code carries the ledger with the move
    # recorded.
    reason = _gated(tmp_path, name="ff", detail=CONTRACT_DETAIL, ledger=parent, stamped=child)
    assert "fast-forward of one lineage" in reason, reason
    assert "`rebase_onto_ref` is only needed to run newer code" in reason, reason

    # A rewind is not a fast-forward, and the gate is then about the state, not the form.
    back = _gated(tmp_path, name="rewind", detail=CONTRACT_DETAIL, ledger=child, stamped=parent)
    assert "the gate stands on the state" in back, back

    # An object the checkout cannot see answers False, which is the fail-closed half of the helper - and
    # it is what a shallow CI clone used to make of this repository's own history.
    nowhere = _gated(tmp_path, name="unseen", detail=CONTRACT_DETAIL, ledger=LEDGER, stamped=STAMPED)
    assert "the gate stands on the state" in nowhere, nowhere


def test_a_real_crash_gate_is_left_unexplained(tmp_path: Path) -> None:
    reason = _gated(tmp_path, name="crash", detail="TypeError: unsupported operand",
                   ledger=LEDGER, stamped=STAMPED)
    assert reason == "operator stop: wrapper_exception (wrapper recorded a terminal failure)", reason
    # A marker whose file cannot be read alongside is reported as unreadable, never as cleared.
    missing = _gated(tmp_path, name="unreadable", detail=CONTRACT_DETAIL, ledger=LEDGER, stamped=None)
    assert "not both readable" in missing, missing



def test_the_ancestry_helper_asks_the_jobs_checkout_and_not_its_own_location() -> None:
    """The launcher fetches this file alone into `$RUNNER_TEMP` and runs it there.

    `__file__` arithmetic then resolves to the runner's home directory, where no `.git` exists, so every
    reachability probe answers False - a fail-closed answer about the *file's location*, presented as a
    verdict about the campaign's commits. `GITHUB_WORKSPACE` is the checkout the leg was measured against,
    so it wins when GitHub sets it; and a helper that cannot ask git still refuses, which is the half of
    the behaviour that must not be "fixed" into an assumption.
    """
    import inspect

    from tools import campaign_supervisor

    source = inspect.getsource(campaign_supervisor)
    assert 'GIT_ROOT = os.environ.get("GITHUB_WORKSPACE") or' in source, source
    assert campaign_supervisor._is_ancestor("deadbeef", "cafebabe") is False
