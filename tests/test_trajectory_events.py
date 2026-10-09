"""Tests for the canonical event vocabulary and the repo-side trajectory deriver.

Item 8 of docs/decisions/2026-10-08-causal-experiment-layer.md: both sides of the
contract, plus the honesty rule that an unmeasurable trajectory is labelled, not zeroed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena import trajectory_metrics as tm  # noqa: E402
from shared import generation_manifest as gm  # noqa: E402
from shared import tool_state as ts  # noqa: E402

MOCO_EASY = "easy,easy,easy,easy,easy,easy"


def _generate(name: str, *extra: str) -> Path:
    directory = ROOT / name
    shutil.rmtree(directory, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, "generate_env.py", "--env", "moco", "--name", name,
         "--difficulty", MOCO_EASY, "--seed", "3", *extra],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return directory


# ---------------------------------------------------------------------------
# the vocabulary itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("read_file", "observe"),
        ("cat", "observe"),
        ("progress", "observe"),
        ("search", "retrieve"),
        ("grep_code", "retrieve"),
        ("apply_patch", "modify"),
        ("write_eval_script", "modify"),
        ("replace_lines", "modify"),
        ("run_train", "execute"),
        ("train", "execute"),
        ("run_visible_tests", "measure"),
        ("eval_model", "measure"),
        ("check_loss", "measure"),
        ("submit", "submit"),
        ("weird_machine_specific_thing", "other"),
        ("", "other"),
    ],
)
def test_the_shared_vocabulary_classifies_actions_consistently(
    action: str, expected: str
) -> None:
    assert ts.classify_action(action) == expected


def test_the_judge_is_never_classified_as_agent_behaviour() -> None:
    """Judge events describe the measurement, not the trajectory that was measured."""
    assert ts.classify_action("hidden_probe", tool="judge") == "judge"
    assert ts.classify_action("hidden_probe", tool="agent") != "judge"


def test_event_records_carry_kind_and_schema_and_nothing_is_dropped() -> None:
    record = ts.event("read_file", tool="agent", path="workspace/prompt.md")
    assert record["kind"] == "observe"
    assert record["schema"] == ts.EVENT_SCHEMA_VERSION
    assert record["details"] == {"path": "workspace/prompt.md"}
    assert set(record) == {"ts", "tool", "action", "status", "summary", "kind", "schema", "details"}
    assert ts.classify_action("run_visible_tests") in ts.KINDS


def test_unclassified_actions_are_kept_and_counted() -> None:
    events = [ts.event(action) for action in ("read_file", "novel_tool_thing", "submit")]
    derived = tm.metrics(events)
    assert derived["counts"]["other"] == 1
    assert derived["uncategorized"] == 1
    assert derived["events"] == 3


# ---------------------------------------------------------------------------
# provenance of the vocabulary
# ---------------------------------------------------------------------------

def test_every_generated_environment_ships_the_contract_without_config_changes() -> None:
    """The vocabulary rides in on the file every environment already copies.

    Adding it as a second shared module would have needed a layout edit in 34 configs,
    which is how a convention becomes 34 slightly different conventions.
    """
    name = "test_traj_shared"
    try:
        directory = _generate(name)
        copied = directory / "agent" / "tools" / "tool_state.py"
        text = copied.read_text(encoding="utf-8")
        assert "EVENT_SCHEMA_VERSION" in text
        assert "def classify_action" in text
        manifest = gm.read_manifest(directory)
        assert manifest["event_schema_version"] == ts.EVENT_SCHEMA_VERSION
        digest = manifest["event_schema_sha256"]
        assert len(digest) == 64
        assert digest == gm.sha256_text((ROOT / "shared" / "tool_state.py").read_text(encoding="utf-8"))
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert ok, errors
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


def test_a_stale_event_schema_is_a_verification_failure_not_a_shrug() -> None:
    name = "test_traj_drift"
    try:
        directory = _generate(name)
        manifest_path = directory / gm.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["event_schema_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        ok, errors = gm.verify_manifest(directory, config_root=ROOT)
        assert not ok
        assert any("event_schema_sha256 mismatch" in error for error in errors), errors
    finally:
        shutil.rmtree(ROOT / name, ignore_errors=True)


# ---------------------------------------------------------------------------
# the host log, the deriver, and the transport limit
# ---------------------------------------------------------------------------

def test_host_events_are_canonical_and_the_deriver_reads_them() -> None:
    episode_id = "trajmetricsepisode"
    episode_dir = ROOT / ".episodes" / episode_id
    try:
        subprocess.run(
            [sys.executable, "env_runner.py", "reset", "--env", "moco", "--difficulty",
             MOCO_EASY, "--seed", "3", "--episode-id", episode_id, "--max-steps", "6",
             "--sandbox", "local"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        for action in ('{"type":"read_file","path":"workspace/prompt.md"}',
                       '{"type":"search","pattern":"temperature"}',
                       '{"type":"write_file","path":"workspace/notes.md","content":"x"}'):
            subprocess.run(
                [sys.executable, "env_runner.py", "step", "--episode", episode_id,
                 "--action", action],
                cwd=ROOT, text=True, capture_output=True, check=True,
            )
        events = [
            json.loads(line)
            for line in (episode_dir / tm.HOST_LOG).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [event.get("action_kind") for event in events] == [
            "lifecycle", "observe", "retrieve", "modify",
        ]
        assert all(event.get("schema") == ts.EVENT_SCHEMA_VERSION for event in events)

        report = tm.summarize(episode_dir, include_agent_log=False)
        assert report["status"] == "measured"
        assert report["host"]["counts"]["retrieve"] == 1
        assert report["gates"]["read_before_first_modify"] is True
        assert report["gates"]["retrieved_rather_than_assumed"] is True
        assert report["gates"]["measured_before_submit"] is False
        assert report["host"]["schemas"] == [ts.EVENT_SCHEMA_VERSION]
    finally:
        shutil.rmtree(episode_dir, ignore_errors=True)


def test_events_written_before_the_vocabulary_are_reclassified_on_read() -> None:
    """An episode recorded with free-form actions is still readable, not unusable."""
    legacy = [
        {"ts": 1.0, "event": "step", "action": {"type": "read_file"}},
        {"ts": 2.0, "event": "step", "action": {"type": "apply_patch"}},
    ]
    derived = tm.metrics(legacy)
    assert derived["first"]["observe"] == 0
    assert derived["first"]["modify"] == 1
    assert derived["schemas"] == [0]


def test_a_missing_event_log_is_not_measurable_and_never_a_zero(tmp_path: Path) -> None:
    report = tm.summarize(tmp_path)
    assert report["status"] == "not_measurable"
    assert "run_eval.sh" in report["transport_note"]
    assert "gates" not in report
    assert report.get("host") is None


def test_agent_claims_are_compared_to_the_host_record_not_trusted(
    tmp_path: Path,
) -> None:
    episode = tmp_path / "episode"
    episode.mkdir(parents=True)
    host = episode / tm.HOST_LOG
    host.write_text(
        "\n".join(
            json.dumps({"ts": 1.0, "event": "step", "action": {"type": "read_file"},
                        "action_kind": "observe", "schema": 1})
            for _ in range(2)
        )
        + "\n",
        encoding="utf-8",
    )
    claimed = episode / tm.AGENT_LOG
    claimed.parent.mkdir(parents=True, exist_ok=True)
    claimed.write_text(
        json.dumps({"ts": 1.5, "tool": "agent", "action": "deep_analysis_pass",
                    "kind": "measure", "schema": 1})
        + "\n",
        encoding="utf-8",
    )
    report = tm.summarize(episode)
    assert report["host"]["counts"]["observe"] == 2
    assert report["agent_claim"]["counts"]["measure"] == 1
    divergence = report["claim_divergence"]
    assert divergence["host_actions_minus_claimed"] == 1
    assert divergence["kinds_only_in_claim"] == ["measure"]
    assert divergence["kinds_only_in_host_log"] == ["observe"]


def test_metrics_survive_an_unparseable_line() -> None:
    """A half-written JSONL line is a real condition in an appended log."""
    assert tm.metrics([{"event": "unparseable", "action_kind": "other", "schema": 0}])[
        "uncategorized"
    ] == 1


def test_cli_reports_and_can_gate_a_campaign_step(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, "arena/trajectory_metrics.py", str(tmp_path / "missing"),
         "--json", str(report_path), "--require-gates"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert proc.returncode == 1
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["status"] == "not_measurable"
