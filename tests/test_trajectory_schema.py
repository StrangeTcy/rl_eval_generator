from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arena.artifacts import RunArtifacts  # noqa: E402
from arena.trajectory_schema import CanonicalEvent, CanonicalTrajectory, canonicalize_trace  # noqa: E402


def test_canonical_events_are_ordered_and_metrics_are_observable() -> None:
    trajectory = CanonicalTrajectory(run_id="run-1", case_id="case-1")
    trajectory.append(CanonicalEvent(0, "observation", {"text": "start"}))
    trajectory.append(CanonicalEvent(1, "action", {"action_type": "inspect", "hypothesis": "A"}))
    trajectory.append(CanonicalEvent(2, "test_execution", {"discriminating": True, "information_gain": 0.5}))
    trajectory.append(CanonicalEvent(3, "reward_proxy_evaluation", {"exploited": True}))
    trajectory.append(CanonicalEvent(4, "action", {"action_type": "edit", "hypothesis": "B"}))
    trajectory.append(CanonicalEvent(5, "action", {"action_type": "inspect", "hypothesis": "A"}))
    trajectory.append(CanonicalEvent(6, "termination", {"reward": 1}))
    metrics = trajectory.metrics()
    assert metrics["hypothesis_switch_count"] == 2
    assert metrics["backtracking_count"] == 1
    assert metrics["time_to_first_discriminating_test"] == 2
    assert metrics["proxy_exploitation_count"] == 1
    assert metrics["information_gain_total"] == 0.5


def test_canonicalize_trace_preserves_process_and_avoids_credentials() -> None:
    trajectory = canonicalize_trace(
        [
            {
                "turn": 0,
                "environment_observation": "observe",
                "environment_info": {"state": "s0"},
                "parsed_action": {"type": "search", "path": "."},
                "raw_model_output": "not a credential",
            },
            {
                "turn": 1,
                "environment_observation": "done",
                "environment_info": {"failure": None},
                "done": True,
                "reward": 1,
            },
        ],
        run_id="run-2",
        case_id="case-2",
    )
    assert trajectory.case_id == "case-2"
    assert [event.event_type for event in trajectory.events] == [
        "observation",
        "action",
        "observation",
        "reward",
        "termination",
    ]
    assert trajectory.metrics()["event_count"] == 5


def test_artifact_finalization_writes_canonical_trajectory(tmp_path: Path) -> None:
    artifacts = RunArtifacts(tmp_path / "runs", "run-3", secret="secret-value")
    artifacts.write_manifest({"api_key": "secret-value", "run_id": "run-3"})
    artifacts.trace(
        {
            "turn": 0,
            "environment_observation": "hello",
            "parsed_action": {"type": "submit"},
            "raw_model_output": "secret-value",
        }
    )
    episode = tmp_path / "episode"
    (episode / "original_workspace").mkdir(parents=True)
    (episode / "env" / "agent" / "workspace").mkdir(parents=True)
    artifacts.finalize(episode_dir=episode, final={"verdict": "PASS"})
    assert artifacts.path("trajectory.json").is_file()
    assert artifacts.path("trajectory_metrics.json").is_file()
    assert '"trajectory_metrics"' in artifacts.path("final.json").read_text(encoding="utf-8")
    assert "secret-value" not in artifacts.path("trajectory.json").read_text(encoding="utf-8")
    assert "secret-value" not in artifacts.path("manifest.json").read_text(encoding="utf-8")
