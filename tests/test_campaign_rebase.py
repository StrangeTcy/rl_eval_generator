"""An operator rebase: new grading code, old ledger - and the refusal to promote anything.

The campaign can be continued in two ways today, and both cost the wrong thing. A resume runs the
commit pinned inside its own state artifact (`tools/campaign_supervisor.py` takes `resume_ref` from
`checkpoint.run.manifest_commit`), so a reference or gate fix can never reach a running lineage. A
fresh dispatch takes the new code and discards the paid T1 result, every banked gate row and the
ceiling counters, then re-bills T1. Both behaviours are correct as safety properties - the resume
because a lineage must not silently change what it measures, the fresh dispatch because it is the
only auditable way to change it - so the fix is not to weaken either. It is to add a third path that
is *explicitly authorized in both directions*: the operator names a new ref, the controller accepts
it only for a grading-context drift, and everything else still refuses.

The unit half below tests the controller's rule. The executed half runs the launcher's own decision
tail - sliced out of the file that gets uploaded, expressions substituted, `bash` invoked - because
a YAML parse once passed on a launcher that crashed at runtime in this repo, and a step's placement
and its array expansions are exactly where that happened before.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.atria_campaign import _record_campaign_intent  # noqa: E402

MANIFEST = {"cases": [{"case_id": "glyph__seed-0", "environment": "glyph", "seed": 0}]}
SHA_A, SHA_B = "a" * 64, "b" * 64


def _intent(tmp: Path, *, sha: str, **kwargs):
    return _record_campaign_intent(
        tmp, MANIFEST, execution_mode="paid", gate_context_sha=sha, profile=None, **kwargs
    )


def test_a_moved_grading_digest_still_refuses_a_resume(tmp_path: Path, monkeypatch) -> None:
    """Without the flag nothing changes: a tick that finds a different code context is refused, so
    the rebase cannot be reached by accident from the scheduler."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    _intent(tmp_path, sha=SHA_A)
    with pytest.raises(ValueError, match="changed: gate_context_sha"):
        _intent(tmp_path, sha=SHA_B)


def test_an_explicit_rebase_records_what_moved_instead_of_pretending_it_did_not(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_WORKFLOW", "Mercury pairwise campaign")
    _intent(tmp_path, sha=SHA_A)
    value = _intent(tmp_path, sha=SHA_B, allow_gate_context_rebase=True)
    assert value["gate_context_sha"] == SHA_B
    assert value["rebased_from_gate_context_sha"] == SHA_A
    assert value["rebased_by"] == "Mercury pairwise campaign"
    assert json.loads((tmp_path / "campaign_intent.json").read_text(encoding="utf-8")) == value
    # A second leg at the new context must not chain the provenance onto itself.
    again = _intent(tmp_path, sha=SHA_B, allow_gate_context_rebase=True)
    assert again["rebased_from_gate_context_sha"] == SHA_A
    assert again["gate_context_sha"] == SHA_B


def test_a_rebase_refuses_a_schedule_event(tmp_path: Path, monkeypatch) -> None:
    """Only a human dispatch may re-pin a lineage. A cron tick deciding its own code context is the
    silent drift the digest exists to prevent."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    _intent(tmp_path, sha=SHA_A)
    with pytest.raises(ValueError, match="not an explicit workflow_dispatch"):
        _intent(tmp_path, sha=SHA_B, allow_gate_context_rebase=True)


def test_a_rebase_does_not_tolerate_a_changed_target(tmp_path: Path, monkeypatch) -> None:
    """The flag is for grading code, not for the thing being measured."""
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    first = {"provider": "atria", "name": "pairwise_a"}
    other = {"provider": "mercury", "name": "pairwise_a", "model": "mercury-2.5"}
    _record_campaign_intent(
        tmp_path, MANIFEST, execution_mode="paid", gate_context_sha=SHA_A, profile=first
    )
    with pytest.raises(ValueError, match="changed: .*provider") as raised:
        _record_campaign_intent(
            tmp_path, MANIFEST, execution_mode="paid", gate_context_sha=SHA_B,
            profile=other, allow_gate_context_rebase=True,
        )
    assert "gate_context_sha" in str(raised.value)  # both fields listed, so the refusal is readable


def _decide_tail(text: str) -> str:
    """The launcher's rebase decision, from the carried-intent check to the end, as runnable bash."""
    workflow = yaml.safe_load(text)
    steps = workflow["jobs"]["campaign"]["steps"]
    decide = next(step for step in steps if str(step.get("name", "")).startswith("Decide"))
    run = decide["run"]
    run = (
        run.replace("${{ inputs.rebase_onto_ref }}", "$INPUT_REBASE")
        .replace("${{ inputs.execution_mode }}", "$INPUT_MODE")
        .replace("${{ inputs.clear_wrapper_stop }}", "$INPUT_CLEAR")
        .replace("${{ github.repository }}", "o/r")
    )
    marker = 'if [ ! -s "$STATE_STAGE/campaign_intent.json" ]; then'
    assert marker in run, "the decision tail must start at the carried-intent check"
    tail = run[run.index(marker):]
    lines = tail.rstrip("\n").split("\n")
    assert lines[-1].strip() == "fi"
    return "\n".join(lines[:-1]) + "\n"


def _run_tail(tmp_path: Path, stage_files: dict[str, str], *, clear: str = "false") -> dict[str, str]:
    stage = tmp_path / "state"
    stage.mkdir(parents=True)
    for name, body in stage_files.items():
        (stage / name).write_text(body, encoding="utf-8")
    out = tmp_path / "github_output"
    script = tmp_path / "decide_tail.sh"
    script.write_text(_decide_tail(LAUNCHER_TEXT), encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin", "STATE_STAGE": str(stage), "GITHUB_OUTPUT": str(out),
        "REBASE": "arena/session-branch", "INPUT_MODE": "paid", "INPUT_CLEAR": clear,
    }
    done = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", f'. "{script}"'], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    return dict(
        line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines() if "=" in line
    )


LAUNCHER_TEXT = (ROOT / "handoff/mercury-pairwise-campaign.yml").read_text(encoding="utf-8")


def test_the_launcher_carries_a_legitimate_ledger_as_a_rebase(tmp_path: Path) -> None:
    """A completed T1 and a readable intent mean the ledger may move onto new code - and the mode
    comes from the intent, not from the dropdown, so `gates_only` stays `gates_only`."""
    outputs = _run_tail(tmp_path, {
        "campaign_intent.json": json.dumps({"execution_mode": "paid", "provider": "mercury"}),
        "t1_same_fact_presentation.json": "{}",
    })
    assert outputs["mode"] == "rebase"
    assert outputs["state_staged"] == "true"
    assert outputs["execution_mode"] == "paid"
    assert outputs["ref"] == "arena/session-branch"


def test_a_rebase_refuses_a_state_with_a_terminal_marker(tmp_path: Path) -> None:
    """A recorded terminal failure is not carried and not cleared. The same file is in
    `tools/inherit_campaign_state.py`'s NOT_INHERITED list, and an operator authorization to run new
    code is not an authorization to walk past the reason a campaign was stopped."""
    outputs = _run_tail(tmp_path, {
        "campaign_intent.json": json.dumps({"execution_mode": "paid"}),
        "t1_same_fact_presentation.json": "{}",
        "wrapper_failed.json": json.dumps({"pause_reason": "exhausted_provider_rate_budget"}),
    })
    assert outputs["mode"] == "none"
    assert "terminal failure" in outputs["reason"]
    assert "exhausted_provider_rate_budget" in outputs["reason"]


def test_an_operator_acknowledgement_carries_the_ledger_past_a_harness_crash(tmp_path: Path) -> None:
    """The one lift that had to exist: without it the marker is a dead end, not a decision point.

    Measured on the live campaign: Mercury run 23 (2026-10-13T00:48:01Z) was refused by exactly this
    guard after run 22's wrapper crashed, and the alternatives were a resume the supervisor refuses and
    a fresh dispatch that drops 190 banked episodes and re-bills T1. A harness crash is not a
    measurement verdict, so an explicit `clear_wrapper_stop=true` on a hand dispatch proceeds - while the
    marker's own rule (tools/atria_campaign.py:1592-1596: cleared at the start of every run) means a
    repeat crash stops again. A spend ceiling, an interrupted T1 and exhausted retries are not lifted.
    """
    crash = json.dumps({"pause_reason": "wrapper_exception", "detail": "RuntimeError: judge exited 1"})
    carried = _run_tail(tmp_path / "lift", {
        "campaign_intent.json": json.dumps({"execution_mode": "paid", "provider": "mercury"}),
        "t1_same_fact_presentation.json": "{}",
        "wrapper_failed.json": crash,
    }, clear="true")
    assert carried["mode"] == "rebase", carried
    assert carried["execution_mode"] == "paid", "the lift must not change what is authorised to bill"
    assert carried["ref"] == "arena/session-branch"

    for reason in ("max_api_calls", "infrastructure_error_retries_exhausted", "wrapper_exception"):
        unacknowledged = _run_tail(tmp_path / f"no-{reason}", {
            "campaign_intent.json": json.dumps({"execution_mode": "paid"}),
            "t1_same_fact_presentation.json": "{}",
            "wrapper_failed.json": json.dumps({"pause_reason": reason}),
        }, clear="false")
        assert unacknowledged["mode"] == "none", (reason, unacknowledged)
        assert "terminal failure" in unacknowledged["reason"], unacknowledged

    for reason in ("max_api_calls", "infrastructure_error_retries_exhausted"):
        still_refused = _run_tail(tmp_path / f"ceil-{reason}", {
            "campaign_intent.json": json.dumps({"execution_mode": "paid"}),
            "t1_same_fact_presentation.json": "{}",
            "wrapper_failed.json": json.dumps({"pause_reason": reason}),
        }, clear="true")
        assert still_refused["mode"] == "none", (reason, still_refused)


def test_the_launcher_refuses_to_replay_an_interrupted_t1(tmp_path: Path) -> None:
    """T1 has no per-trial resume ledger, so a carried-but-unfinished T1 is an operator stop under a
    rebase exactly as it is under a tick: the state that saves money must not become the state that
    spends it twice."""
    outputs = _run_tail(tmp_path, {
        "campaign_intent.json": json.dumps({"execution_mode": "paid"}),
        "t1_started.json": "{}",
    })
    assert outputs["mode"] == "none"
    assert "interrupted" in outputs["reason"]


@pytest.mark.parametrize(
    "intent_body",
    ["{}", '{"execution_mode": "sometimes"}', "not json at all"],
)
def test_the_launcher_refuses_to_guess_what_may_bill(tmp_path: Path, intent_body: str) -> None:
    outputs = _run_tail(tmp_path, {"campaign_intent.json": intent_body})
    assert outputs["mode"] == "none"
    assert "execution mode" in outputs["reason"]


def test_the_launcher_falls_back_to_fresh_when_there_is_nothing_to_carry(tmp_path: Path) -> None:
    outputs = _run_tail(tmp_path, {"some_other_file.json": "{}"})
    assert outputs["mode"] == "fresh"
    assert outputs["ref"] == "arena/session-branch"
    assert "campaign intent" in outputs["reason"]


@pytest.mark.parametrize("slug", ["mercury", "reasoning-atria"])
def test_both_pairwise_launchers_offer_the_rebase_and_gate_on_it(slug: str) -> None:
    handoff = ROOT / f"handoff/{slug}-pairwise-campaign.yml"
    example = ROOT / f"docs/workflows/{slug}-pairwise-campaign.yml.example"
    text = handoff.read_text(encoding="utf-8")
    assert text == example.read_text(encoding="utf-8"), f"{slug}: handoff copy and docs example drifted"
    workflow = yaml.safe_load(text)
    top = workflow.get(True, workflow.get("on"))  # `on:` is a YAML 1.1 boolean key
    inputs = top["workflow_dispatch"]["inputs"]
    assert inputs["rebase_onto_ref"]["default"] == ""
    assert inputs["rebase_onto_ref"]["required"] is False
    assert "carried intent" in inputs["rebase_onto_ref"]["description"]

    steps = workflow["jobs"]["campaign"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    decide = names.index(next(n for n in names if n.startswith("Decide")))
    initialise = names.index("Initialize fresh campaign state")
    preflight = names.index("Refuse a plan whose exact-instance reference cannot be applied")
    assert "rebase_onto_ref" in steps[decide]["run"]
    assert steps[decide]["run"].index("rebase_onto_ref") < steps[decide]["run"].index("LATEST="), (
        f"{slug}: the rebase must be decided before the resume path can short-circuit it"
    )
    # A rebase carries state, so it must never be treated as a fresh initialization...
    assert steps[initialise]["if"] == "steps.mode.outputs.mode != 'none' && steps.mode.outputs.mode == 'fresh'"
    # ...but it does run new grading code, so the provider-free preflight cannot skip it.
    assert "rebase" in steps[preflight]["if"] and "fresh" in steps[preflight]["if"]

    billing = next(step for step in steps if "Run T1" in str(step.get("name", "")))
    assert billing["run"].count("--rebase-intent") == 1
    assert billing["run"].count('${REBASE_ARG[@]+"${REBASE_ARG[@]}"}') == 2
    # The step holds two `EXECUTION_MODE = paid` branches (T1 and the campaign), so the ordering
    # check is against the campaign invocation itself: the array must exist before either call.
    assert "REBASE_ARG=()" in billing["run"]
    assert billing["run"].index("REBASE_ARG=()") < billing["run"].index("--allow-provider")
    inherit = next(step for step in steps if "Inherit" in str(step.get("name", "")))
    assert "--rebase-intent" not in inherit["run"]
