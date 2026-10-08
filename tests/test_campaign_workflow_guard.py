"""The campaign workflow must keep its state-regression guard.

The guard in the "Stage campaign state for upload" step compares the episode
count of the state artifact restored on entry against the checkpoint left on
exit. When progress went backwards it uploads the RESTORED copy and fails the
leg loudly, so a damaged state can never become the newest artifact -- which is
what the supervisor would otherwise resume from forever.

This exists because the guard was already silently dropped once. It was present
in the documentation copy and absent from the deployed workflow, nothing
noticed, and the deployed chained workflow ended up relying solely on the
GITHUB_EVENT_NAME override, which has never been executed on a runner. If that
override silently fails, a chained leg wipes, the damaged state is uploaded as
newest, and the chain continues -- the exact loop that destroyed 73 banked
episodes and ~12h of gate rows on 2026-09-30.

Deployment model, which is why the rules below are not uniform:

  * docs/workflows/atria-campaign.yml.example
        The deployable replacement, and the file an operator copies to
        .github/workflows/atria-campaign.yml. It is the source of truth, so it
        must always carry the guard.
  * docs/workflows/atria-campaign-chained.yml.example
        The same plus the self-dispatch chain, ready but not the default.
  * .github/workflows/atria-campaign.yml
        Copied by hand, not pushed: the automation token has no `workflows`
        permission, so this branch cannot modify that path. It is therefore
        held to the safety-critical rule only -- if it chains, it must be
        guarded -- and not to the unconditional one.

The guard is workflow-level on purpose. A campaign checks out a pinned ref, so
a fix in tools/ cannot reach an in-flight campaign, while this step is read from
the default branch on the very next leg.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEPLOYED = ROOT / ".github" / "workflows" / "atria-campaign.yml"
SAFE_DEFAULT = ROOT / "docs" / "workflows" / "atria-campaign.yml.example"
CHAINED = ROOT / "docs" / "workflows" / "atria-campaign-chained.yml.example"

# The guard must be in both deployable sources; the deployed copy is hand-copied
# and may legitimately lag, so it is only held to the chaining rule below.
SOURCES_OF_TRUTH = (SAFE_DEFAULT, CHAINED)
ALL_CAMPAIGN_WORKFLOWS = (DEPLOYED, SAFE_DEFAULT, CHAINED)

STAGE_STEP_NAME = "Stage campaign state for upload"
CHAIN_STEP_NAME = "Chain the next dispatch"
CAMPAIGN_STEP_NAME = "Run the covering campaign (fresh or resumed)"

# The guard must keep all of these. Each is load-bearing: without the comparison
# there is nothing to detect, without the restored copy there is nothing safe to
# upload, and without the published verdict the chain cannot be suppressed.
GUARD_TOKENS = (
    ('RESTORED="$RUNNER_TEMP/atria_state/suite_checkpoint.json"',
     "must count episodes in the state restored on entry"),
    ("BEFORE", "must record the episode count on entry"),
    ("AFTER", "must record the episode count on exit"),
    ('[ "$BEFORE" -gt 0 ] && [ "$AFTER" -lt "$BEFORE" ]',
     "must fire when a leg ends with fewer episodes than it started with"),
    ('cp -a "$RUNNER_TEMP/atria_state/." "$STAGED/"',
     "must stage the RESTORED state so the good artifact stays newest"),
    ('echo "regressed=true" >> "$GITHUB_OUTPUT"',
     "must publish the verdict for the chain condition"),
    ("exit 1", "must fail loudly rather than uploading a regressed state quietly"),
)


def _steps(path: Path) -> list[dict]:
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return list(workflow["jobs"]["campaign"]["steps"])


def _step(path: Path, name: str) -> dict | None:
    return next((s for s in _steps(path) if s.get("name") == name), None)


def _stage_body(path: Path) -> str:
    stage = _step(path, STAGE_STEP_NAME)
    assert stage is not None, f"{path.name}: no {STAGE_STEP_NAME!r} step"
    return stage.get("run", "")


def test_deployable_sources_of_truth_keep_the_regression_guard() -> None:
    for path in SOURCES_OF_TRUTH:
        # The guard publishes its verdict so the chain can be suppressed on a
        # leg that lost progress. Without the id, the chain's condition silently
        # evaluates empty and the suppression is dead code.
        stage = _step(path, STAGE_STEP_NAME)
        assert stage is not None, f"{path.name}: no {STAGE_STEP_NAME!r} step"
        assert stage.get("id") == "stage", (
            f"{path.name}: {STAGE_STEP_NAME!r} must keep id: stage so the chain "
            "condition can read its regressed output"
        )
        body = stage.get("run", "")
        for token, why in GUARD_TOKENS:
            assert token in body, f"{path.name}: guard is missing {token!r} ({why})"


def test_no_campaign_workflow_chains_without_the_guard() -> None:
    """Chaining repeats a leg automatically, and repeating a destructive one is
    how a single wipe became a self-sustaining loop. A workflow that dispatches
    its own continuation is the dangerous configuration, so it is the one this
    test refuses to let through unguarded -- in any of the three files."""
    for path in ALL_CAMPAIGN_WORKFLOWS:
        chain = _step(path, CHAIN_STEP_NAME)
        if chain is None:
            continue
        body = _stage_body(path)
        missing = [token for token, _ in GUARD_TOKENS if token not in body]
        assert not missing, (
            f"{path.name}: has a {CHAIN_STEP_NAME!r} step but its "
            f"{STAGE_STEP_NAME!r} step is missing {missing}; a chained leg with no "
            "guard can bury the good state artifact with a damaged one"
        )
        condition = chain.get("if", "")
        assert "steps.stage.outputs.regressed != 'true'" in condition, (
            f"{path.name}: {CHAIN_STEP_NAME!r} must not run after a regression; "
            f"its if: is {condition!r}"
        )


def test_a_chained_campaign_presents_a_resume_as_a_resume() -> None:
    """Once self-dispatch exists a resume arrives as a workflow_dispatch, and
    the controller must not observe that event name on a resume. Only the
    chaining launcher needs this: with cron-only continuation every resume
    really is a schedule event.

    Two mechanisms are accepted, because the deployed workflow legitimately
    moved from (1) to (2) after the workflow-level override had never been
    executed on a runner:

      1. a step-level env override that presents a resume as a non-dispatch
         event (`steps.mode.outputs.mode == 'resume'` in GITHUB_EVENT_NAME),
         as in the chained example source of truth;
      2. unsetting GITHUB_EVENT_NAME in the controller's child process on a
         resume-gated branch (`env -u GITHUB_EVENT_NAME`), as in the deployed
         workflow, which additionally passes explicit --allow-provider there.

    Both guarantee the controller treats the leg as a resume; the controller
    separately refuses any destructive inferred fresh start without --fresh."""
    for path in ALL_CAMPAIGN_WORKFLOWS:
        if _step(path, CHAIN_STEP_NAME) is None:
            continue
        campaign = _step(path, CAMPAIGN_STEP_NAME)
        assert campaign is not None, f"{path.name}: no campaign run step"
        override = (campaign.get("env") or {}).get("GITHUB_EVENT_NAME", "")
        via_override = "steps.mode.outputs.mode == 'resume'" in override
        body = campaign.get("run", "")
        resume_gate = body.find('[ "$MODE" = "resume" ]')
        unset_at = body.find("env -u GITHUB_EVENT_NAME")
        via_unset = resume_gate != -1 and unset_at != -1 and resume_gate < unset_at
        assert via_override or via_unset, (
            f"{path.name}: a chained resume must reach the controller without "
            f"GITHUB_EVENT_NAME=workflow_dispatch; env override is {override!r} "
            "and no resume-gated `env -u GITHUB_EVENT_NAME` branch was found"
        )


def test_the_safe_default_does_not_re_enable_chaining() -> None:
    """atria-campaign.yml.example is what gets copied onto the live workflow, so
    it must not smuggle in the self-dispatch chain. Adding the guard is meant to
    be behaviourally inert; adding a chain is not. The chained variant is kept
    as a separate, explicit file so that decision stays separate."""
    workflow = yaml.load(SAFE_DEFAULT.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    inputs = triggers["workflow_dispatch"].get("inputs") or {}
    steps = [s.get("name") for s in workflow["jobs"]["campaign"]["steps"]]

    assert CHAIN_STEP_NAME not in steps, (
        "the safe default must stay cron-only; the chain belongs in "
        "atria-campaign-chained.yml.example"
    )
    assert "continuation" not in inputs, (
        "the safe default must not accept a continuation input; a ticked box "
        "turns a copy into a chained dispatch"
    )
    assert workflow["permissions"].get("actions") == "read", (
        "the safe default does not dispatch anything, so it must not request "
        "actions: write"
    )
    assert "workflow_dispatch" in triggers and "schedule" in triggers

    # ...and the chained variant really is the one carrying the chain.
    chained = yaml.load(CHAINED.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert CHAIN_STEP_NAME in [
        s.get("name") for s in chained["jobs"]["campaign"]["steps"]
    ]
    assert chained["permissions"].get("actions") == "write"


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None,
                    reason="needs bash and jq to execute the guard as written")
@pytest.mark.parametrize("path", SOURCES_OF_TRUTH, ids=lambda p: p.name)
def test_the_guard_as_written_protects_the_restored_state(
    path: Path, tmp_path: Path
) -> None:
    """Execute the guard exactly as the workflow would, rather than trusting
    that the shell it contains does what its comments claim.

    A leg that ends with fewer episodes than it restored must upload the
    restored copy and fail. A leg that ends with the same number (paused early)
    or more (made progress) must pass its own state through and succeed --
    otherwise a campaign could never pause and the guard would cry wolf on
    every normal leg.
    """
    runner_temp = tmp_path / "runner"
    (runner_temp / "atria_state").mkdir(parents=True)
    workspace = tmp_path / "workspace"
    (workspace / "runs" / "atria_campaign").mkdir(parents=True)

    # "${{ runner.temp }}" is the only Actions-specific token in this step.
    script = _stage_body(path).replace("${{ runner.temp }}", str(runner_temp))
    guard = tmp_path / "guard.sh"
    guard.write_text(script, encoding="utf-8")

    def write_checkpoint(target: Path, episodes: int) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"results": [{"case_id": f"case-{i}"} for i in range(episodes)]}),
            encoding="utf-8",
        )

    def run(before: int, after: int) -> tuple[int, int, str]:
        # The restored artifact is what the leg found on entry; the workspace
        # checkpoint is what it left behind. They are written separately because
        # the whole guard is the comparison between them.
        restored = runner_temp / "atria_state" / "suite_checkpoint.json"
        current = workspace / "runs" / "atria_campaign" / "suite_checkpoint.json"
        write_checkpoint(restored, before)
        write_checkpoint(current, after)
        (runner_temp / "atria_upload").mkdir(parents=True, exist_ok=True)
        env = {
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(tmp_path / "gh_output"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        (tmp_path / "gh_output").write_text("", encoding="utf-8")
        proc = subprocess.run(
            ["bash", str(guard)], cwd=workspace, env=env,
            capture_output=True, text=True, timeout=60,
        )
        uploaded = runner_temp / "atria_upload" / "suite_checkpoint.json"
        staged = (
            len(json.loads(uploaded.read_text(encoding="utf-8"))["results"])
            if uploaded.is_file() else -1
        )
        verdict = (tmp_path / "gh_output").read_text(encoding="utf-8")
        return proc.returncode, staged, verdict

    # The loss: upload the RESTORED 73 episodes, fail loudly, suppress the chain.
    code, staged, verdict = run(before=73, after=18)
    assert code == 1, "a leg that lost progress must fail loudly"
    assert staged == 73, "the restored state must be uploaded, not the damaged one"
    assert "regressed=true" in verdict

    # Paused without progress: same count, allowed, and the chain may continue.
    code, staged, verdict = run(before=73, after=73)
    assert code == 0, "a leg that paused at the same count is not a regression"
    assert staged == 73
    assert "regressed=false" in verdict

    # Made progress: allowed.
    code, staged, verdict = run(before=73, after=81)
    assert (code, staged) == (0, 81)
    assert "regressed=false" in verdict

    # A genuine first dispatch has nothing restored, so before=0 and any count
    # is legitimate; the guard must not fire on it.
    code, staged, verdict = run(before=0, after=0)
    assert (code, staged) == (0, 0)
    assert "regressed=false" in verdict
