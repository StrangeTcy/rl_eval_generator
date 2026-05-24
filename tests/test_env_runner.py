import json
import subprocess
import sys
from pathlib import Path

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
        "easy,easy,easy,easy,easy,easy,easy",
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
