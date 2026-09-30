"""The campaign workflow must keep its state-regression guard.

The guard in the "Stage campaign state for upload" step compares the episode
count of the state artifact restored on entry against the checkpoint left on
exit. When progress went backwards it uploads the RESTORED copy and fails the
leg loudly, so a damaged state can never become the newest artifact -- which is
what the supervisor would otherwise resume from forever.

This exists because the guard was already silently dropped once. It was present
in the documentation copy and absent from the deployed workflow, nothing
noticed, and the deployed workflow tried to override the protected GITHUB_EVENT_NAME
in a step env mapping. Run 38 logged `schedule` there, but the controller still
lost the restored 73-result checkpoint. The safe default below resumes on a real schedule event or an explicit
Continue checkbox instead of relying on that ineffective override.

Deployment model, which is why the rules below are not uniform:

  * docs/workflows/atria-campaign.yml.example
        The deployable replacement, and the file an operator copies to
        .github/workflows/atria-campaign.yml. It is the source of truth, so it
        must always carry the guard.
  * docs/workflows/atria-campaign-chained.yml.example
        The same plus the self-dispatch chain, ready but not the default.
  * .github/workflows/atria-campaign.yml
        A hand-copied deployment snapshot. This task deliberately does not
        modify it; operators apply the safe-default file above when deploying.
        Tests treat the docs file as the source of truth, not this potentially
        stale snapshot.

The guard is workflow-level on purpose. A campaign checks out a pinned ref, so
a fix in tools/ cannot reach an in-flight campaign, while this step is read from
the default branch on the very next leg.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAFE_DEFAULT = ROOT / "docs" / "workflows" / "atria-campaign.yml.example"
CHAINED = ROOT / "docs" / "workflows" / "atria-campaign-chained.yml.example"

# These two docs workflows are deployable sources of truth. The hand-copied
# deployed snapshot is intentionally outside the scope of this docs-only change.
SOURCES_OF_TRUTH = (SAFE_DEFAULT, CHAINED)

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


def test_no_documented_campaign_workflow_chains_without_the_guard() -> None:
    """The deployable docs templates may not chain without their state guard.

    The live workflow is a hand-copied deployment snapshot and is not modified
    by this docs-only change; operators copy the verified safe default to it.
    """
    for path in SOURCES_OF_TRUTH:
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


def test_safe_default_resume_uses_the_real_schedule_event() -> None:
    """The pinned controller infers freshness from GITHUB_EVENT_NAME. The
    deployable safe default resumes on a real schedule event; it must not rely
    on trying to overwrite GitHub's protected GITHUB_* variables."""
    workflow = yaml.load(SAFE_DEFAULT.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers

    mode = _step(SAFE_DEFAULT, "Decide dispatch versus supervised resume")
    campaign = _step(SAFE_DEFAULT, CAMPAIGN_STEP_NAME)
    assert mode is not None and campaign is not None
    assert 'if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then' in mode.get("run", "")
    assert '[ "$CONTINUATION" != "true" ]' in mode.get("run", "")
    assert "mode=fresh" in mode.get("run", "")
    assert "GITHUB_EVENT_NAME" not in (campaign.get("env") or {})
    assert "GITHUB_EVENT_NAME=" not in campaign.get("run", "")
    assert "env -u GITHUB_EVENT_NAME" in campaign.get("run", "")
    assert "--allow-provider" in campaign.get("run", "")
    body = mode.get("run", "")
    assert 'MANUAL_CONTINUE="false"' in body
    assert 'MANUAL_CONTINUE="true"' in body
    assert "manual_continue=manual_continue" in body
    assert "age < 1200 and not manual_continue" in body


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None,
                    reason="needs bash and jq to execute the workflow mode decision")
@pytest.mark.parametrize(
    ("event_name", "continuation", "expected_mode", "expected_artifact_lookup"),
    [
        ("workflow_dispatch", "false", "fresh", False),
        ("workflow_dispatch", "true", "none", True),
        ("schedule", "false", "none", True),
    ],
)
def test_continue_checkbox_selects_artifact_resume_not_the_ui_ref(
    tmp_path: Path,
    event_name: str,
    continuation: str,
    expected_mode: str,
    expected_artifact_lookup: bool,
) -> None:
    """Execute the workflow's real mode step with a stub API.

    An unticked manual dispatch is fresh and uses the entered code ref. A
    checked dispatch and a schedule both go to the artifact lookup path; the
    test's empty artifact list makes those paths no-op safely.
    """
    mode = _step(SAFE_DEFAULT, "Decide dispatch versus supervised resume")
    assert mode is not None
    body = mode.get("run", "")
    for expression, value in (
        ("${{ github.event_name }}", event_name),
        ("${{ inputs.continuation }}", continuation),
        ("${{ inputs.ref }}", "ui-selected-code-ref"),
        ("${{ github.repository }}", "owner/repository"),
    ):
        body = body.replace(expression, value)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_path = tmp_path / "gh-calls.txt"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$GH_CALLS\"\n"
        "case \"$*\" in\n"
        "  *'actions/artifacts?per_page=100'*) printf 'null\\n' ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output_path = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env.get('PATH', '')}",
        "GITHUB_REPOSITORY": "owner/repository",
        "GITHUB_OUTPUT": str(output_path),
        "GH_CALLS": str(calls_path),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
    })
    subprocess.run(["bash", "-c", body], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True)

    output = output_path.read_text(encoding="utf-8")
    calls = calls_path.read_text(encoding="utf-8").splitlines() if calls_path.exists() else []
    assert f"mode={expected_mode}" in output
    assert ("actions/artifacts?per_page=100" in " ".join(calls)) is expected_artifact_lookup
    if event_name == "workflow_dispatch" and continuation == "false":
        assert "ref=ui-selected-code-ref" in output
    else:
        assert "ref=ui-selected-code-ref" not in output



@pytest.mark.skipif(
    any(shutil.which(command) is None for command in ("bash", "jq", "unzip", "base64")),
    reason="needs bash, jq, unzip, and base64 to execute the artifact decision path",
)
@pytest.mark.parametrize("legacy_pinned_supervisor", [False, True], ids=["current", "legacy-pinned"])
def test_checked_continue_restores_artifact_and_uses_its_pinned_ref(
    tmp_path: Path, legacy_pinned_supervisor: bool,
) -> None:
    """A checked Continue resumes an in-cooldown artifact from its pinned ref.

    Exercise both the new supervisor API and the one-argument supervisor
    already pinned by an in-flight campaign. The manual override may bypass only
    the transient cooldown; it must still reuse the checkpoint's exact code ref.
    """
    mode = _step(SAFE_DEFAULT, "Decide dispatch versus supervised resume")
    assert mode is not None
    body = mode.get("run", "")
    for expression, value in (
        ("${{ github.event_name }}", "workflow_dispatch"),
        ("${{ inputs.continuation }}", "true"),
        ("${{ inputs.ref }}", "ui-selected-fresh-ref"),
        ("${{ github.repository }}", "owner/repository"),
    ):
        body = body.replace(expression, value)

    pinned_ref = "a" * 40
    state_dir = tmp_path / "artifact-state"
    state_dir.mkdir()
    (state_dir / "campaign_ref.txt").write_text("operator-branch\n", encoding="utf-8")
    (state_dir / "campaign_intent.json").write_text(json.dumps({
        "schema_version": 1,
        "provider": "atria",
        "execution_mode": "paid",
        "case_manifest_sha256": "b" * 64,
        "gate_context_sha": pinned_ref,
    }), encoding="utf-8")
    recent = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (state_dir / "suite_checkpoint.json").write_text(json.dumps({
        "paused": True,
        "pause_reason": "infrastructure_error",
        "updated_at": recent,
        "infrastructure_retries": {"case-72": 3},
        "results": [{"case_id": f"case-{i}"} for i in range(73)],
        "run": {"manifest_commit": pinned_ref},
    }), encoding="utf-8")
    (state_dir / "campaign_report.json").write_text(json.dumps({
        "status": "paused",
        "pause_reason": "infrastructure_error",
        "resumable": True,
    }), encoding="utf-8")
    archive = tmp_path / "state.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in state_dir.iterdir():
            bundle.write(path, path.name)

    if legacy_pinned_supervisor:
        supervisor_source = b"""
import json, os
from datetime import datetime, timezone
def decide_tick(state_dir):
    checkpoint = json.load(open(os.path.join(state_dir, "suite_checkpoint.json")))
    updated = str(checkpoint.get("updated_at") or "")
    if updated:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated.replace("Z", "+00:00"))).total_seconds()
        if age < 1200:
            return {"mode": "none", "reason": f"backoff: paused {int(age)}s ago, retry in {int(1200-age)}s"}
    return {"mode": "resume", "execution_mode": "paid", "ref": checkpoint["run"]["manifest_commit"], "reason": f"resuming after {checkpoint['pause_reason']}"}
"""
    else:
        supervisor_source = (ROOT / "tools" / "campaign_supervisor.py").read_bytes()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_path = tmp_path / "gh-calls.txt"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$GH_CALLS\"\n"
        "case \"$*\" in\n"
        "  *'actions/artifacts?per_page=100'*) printf '%s\\n' \"$FAKE_ARTIFACT_JSON\" ;;\n"
        "  *'actions/artifacts/55/zip'*) cat \"$FAKE_STATE_ZIP\" ;;\n"
        "  *'contents/experiments/atria_campaign.yaml?ref='*) printf '%s\\n' \"$FAKE_PROFILE_CONTENT\" ;;\n"
        "  *'contents/tools/campaign_supervisor.py?ref='*) printf '%s\\n' \"$FAKE_SUPERVISOR_CONTENT\" ;;\n"
        "  *'actions/runs?status=in_progress&per_page=100'*) printf '0\\n' ;;\n"
        "  *) echo \"unexpected gh call: $*\" >&2; exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env.get('PATH', '')}",
        "GITHUB_REPOSITORY": "owner/repository",
        "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
        "GH_CALLS": str(calls_path),
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "FAKE_ARTIFACT_JSON": json.dumps({
            "id": 55,
            "name": "atria-campaign-state-38",
            "created_at": "2026-09-30T20:05:48Z",
            "expired": False,
        }),
        "FAKE_STATE_ZIP": str(archive),
        "FAKE_PROFILE_CONTENT": base64.b64encode(
            b"manual_gate_blocked_exclusions: []\\n"
        ).decode("ascii"),
        "FAKE_SUPERVISOR_CONTENT": base64.b64encode(supervisor_source).decode("ascii"),
    })
    subprocess.run(["bash", "-c", body], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True, timeout=60)

    output = (tmp_path / "github-output.txt").read_text(encoding="utf-8")
    assert "mode=resume" in output
    assert f"ref={pinned_ref}" in output
    assert "reason=manual Continue bypassed cooldown;" in output
    assert "ref=ui-selected-fresh-ref" not in output
    calls = calls_path.read_text(encoding="utf-8").splitlines()
    assert any("actions/artifacts?per_page=100" in call for call in calls)
    assert any("actions/artifacts/55/zip" in call for call in calls)
    assert any("campaign_supervisor.py?ref=operator-branch" in call for call in calls)



@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash to execute the manual resume command")
def test_manual_continue_unsets_event_only_for_controller_child(tmp_path: Path) -> None:
    """A checked manual resume must not override the runner event, but its
    controller child must take the non-destructive resume path and explicit
    provider authorization.
    """
    campaign = _step(SAFE_DEFAULT, CAMPAIGN_STEP_NAME)
    assert campaign is not None
    body = campaign.get("run", "")
    start = body.index("# A checked manual Continue")
    end = body.index("rc=$?", start)
    command_block = body[start:end]
    command_block = command_block.replace("${{ github.event_name }}", "workflow_dispatch")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "${GITHUB_EVENT_NAME-UNSET}" > "$CONTROLLER_EVENT"
printf '%s\\n' "$*" > "$CONTROLLER_ARGS"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env.get('PATH', '')}",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "CONTROLLER_EVENT": str(tmp_path / "child-event.txt"),
        "CONTROLLER_ARGS": str(tmp_path / "child-args.txt"),
    })
    script = "set -euo pipefail\nMODE=resume\n" + command_block + "\nrc=$?\nexit $rc\n"
    subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True)

    assert (tmp_path / "child-event.txt").read_text(encoding="utf-8").strip() == "UNSET"
    args = (tmp_path / "child-args.txt").read_text(encoding="utf-8")
    assert "--allow-provider" in args
    assert "--profile experiments/atria_campaign.yaml" in args
    assert "--out runs/atria_campaign" in args


def test_safe_default_resume_routes_the_restored_sidecar_to_issue_three() -> None:
    campaign = _step(SAFE_DEFAULT, CAMPAIGN_STEP_NAME)
    assert campaign is not None
    body = campaign.get("run", "")
    assert 'STATUS_ISSUE=3' in body
    assert 'if [ "$MODE" = "resume" ]; then' in body
    assert 'issues/$STATUS_ISSUE/comments?per_page=100' in body
    assert "del(.comment_id)" in body
    assert "campaign_status_comment.json" in body
    assert "Live Atria campaign status is maintained in the latest comment." in body
    assert "POST /repos" not in body
    assert "## Campaign watchdog" not in body


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None,
                    reason="needs bash and jq to execute the workflow routing block")
@pytest.mark.parametrize("comment_id", ["731", ""])
def test_resume_routing_overwrites_stale_sidecar_identity_without_opening_issue(
    tmp_path: Path, comment_id: str
) -> None:
    """Execute the actual routing block against a restored state that points to
    Issue #10. A discovered Issue #3 comment is reused; otherwise the seed is
    only issue_number=3, which makes the pinned sidecar create a comment on #3
    rather than POST a new Issue.
    """
    campaign = _step(SAFE_DEFAULT, CAMPAIGN_STEP_NAME)
    assert campaign is not None
    body = campaign.get("run", "")
    start = body.index("STATUS_ISSUE=3")
    end = body.index("python tools/campaign_status_sidecar.py", start)
    routing = body[start:end]
    script = "set -euo pipefail\nMODE=resume\n" + routing + "\n"

    state_dir = tmp_path / "runs" / "atria_campaign"
    state_dir.mkdir(parents=True)
    state_path = state_dir / "campaign_status_comment.json"
    state_path.write_text(json.dumps({
        "issue_number": 10,
        "comment_id": 1010,
        "campaign_started_at": "2026-09-29T13:34:40Z",
    }), encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls_path = tmp_path / "gh-calls.txt"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$GH_CALLS\"\n"
        "case \"$*\" in\n"
        "  *'issues/3/comments?per_page=100'*)\n"
        "    [ -z \"$FAKE_COMMENT_ID\" ] || printf '%s\\n' \"$FAKE_COMMENT_ID\"\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": f"{fake_bin}:{env.get('PATH', '')}",
        "GITHUB_REPOSITORY": "owner/repository",
        "GH_CALLS": str(calls_path),
        "FAKE_COMMENT_ID": comment_id,
    })

    subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["issue_number"] == 3
    assert state.get("comment_id") == (int(comment_id) if comment_id else None)
    assert state["campaign_started_at"] == "2026-09-29T13:34:40Z"
    calls = calls_path.read_text(encoding="utf-8").splitlines()
    assert any("issues/3/comments?per_page=100" in call for call in calls)
    assert any("-X PATCH repos/owner/repository/issues/3" in call for call in calls)
    assert not any("POST" in call and call.rstrip().endswith("/issues") for call in calls)


def test_the_safe_default_does_not_re_enable_chaining() -> None:
    """The safe default may resume by schedule or explicit operator checkbox,
    but it must not self-dispatch. The chained variant stays separate because
    it requires actions: write and can repeat a bad leg automatically."""
    workflow = yaml.load(SAFE_DEFAULT.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    inputs = triggers["workflow_dispatch"].get("inputs") or {}
    steps = [s.get("name") for s in workflow["jobs"]["campaign"]["steps"]]

    assert CHAIN_STEP_NAME not in steps, (
        "the safe default may offer an operator Continue checkbox, but it must "
        "not self-dispatch; chaining belongs in atria-campaign-chained.yml.example"
    )
    assert inputs.get("continuation", {}).get("type") == "boolean", (
        "manual resume must be an explicit boolean checkbox, not an ambiguous "
        "text field or an automatic self-dispatch"
    )
    assert inputs["continuation"].get("default") == "false"
    assert "latest eligible campaign artifact" in inputs["continuation"].get("description", "")
    assert "fresh campaign only" in inputs.get("ref", {}).get("description", "")
    assert "chain_depth" not in inputs
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
