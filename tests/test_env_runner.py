import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import env_runner
from arena.episode import EpisodeOptions, run_episode

ROOT = Path(__file__).resolve().parents[1]


def run_runner(*args):
    return subprocess.run(
        [sys.executable, "env_runner.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_env_runner_reset_and_step():
    episode = "pytest_rope_episode"
    subprocess.run(["rm", "-rf", f".episodes/{episode}"], cwd=ROOT)
    proc = run_runner(
        "reset",
        "--env",
        "rope",
        "--episode-id",
        episode,
        "--difficulty",
        "easy,easy,easy,easy,easy,easy,easy,easy",
        "--seed",
        "1",
        "--max-steps",
        "5",
    )
    data = json.loads(proc.stdout)
    assert data["episode_id"] == episode
    assert data["done"] is False

    proc = run_runner("step", "--episode", episode, "--action", json.dumps({"type": "read_file", "path": "prompt.md"}))
    data = json.loads(proc.stdout)
    assert "Fix RoPE" in data["observation"]
    assert data["reward"] == 0.0
    assert data["done"] is False

    proc = run_runner("step", "--episode", episode, "--action", json.dumps({"cmd": "ls"}))
    data = json.loads(proc.stdout)
    assert "model.py" in data["observation"]

    subprocess.run(["rm", "-rf", f".episodes/{episode}"], cwd=ROOT)


def test_episode_id_cannot_escape_runner_or_controller_cleanup(tmp_path, monkeypatch):
    outside = tmp_path / "victim"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("leave this alone", encoding="utf-8")
    monkeypatch.setattr(env_runner, "EPISODES_DIR", tmp_path / "episodes")

    with pytest.raises(ValueError, match="Invalid episode ID"):
        env_runner.reset(SimpleNamespace(episode_id="../victim", env="glyph", sandbox="local"))
    with pytest.raises(ValueError, match="Invalid episode ID"):
        env_runner._load_state("/tmp/victim")
    with pytest.raises(ValueError, match="Invalid episode ID"):
        env_runner._load_state("..")
    with pytest.raises(ValueError, match="Invalid episode ID"):
        run_episode(
            EpisodeOptions(
                provider="custom",
                model="offline/pinned",
                env="glyph",
                difficulty="easy,easy,easy,easy,easy,easy",
                episode_id="../victim",
                out=tmp_path / "runs",
            )
        )
    assert marker.read_text(encoding="utf-8") == "leave this alone"
    assert not (tmp_path / "episodes").exists()
    assert not (tmp_path / "runs").exists()
