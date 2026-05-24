#!/usr/bin/env python3
"""Minimal reset/step runner for generated evaluation environments.

This is intentionally small: it gives the repository a gym-like interaction
surface without introducing a server, Gym dependency, or persistent Docker
session. Episodes are stored under `.episodes/` and actions are JSON objects.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
EPISODES_DIR = ROOT / ".episodes"
DEFAULT_MAX_STEPS = 40
MAX_OBSERVATION_CHARS = 12000


def _json(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, indent=2))


def _safe_join(root: Path, rel: str) -> Path:
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"Path escapes workspace: {rel}")
    return candidate


def _load_state(episode_id: str) -> dict[str, Any]:
    path = EPISODES_DIR / episode_id / "state.json"
    if not path.is_file():
        raise SystemExit(f"Unknown episode: {episode_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(state: dict[str, Any]) -> None:
    path = EPISODES_DIR / state["episode_id"] / "state.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _obs(text: str) -> str:
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text
    return text[:MAX_OBSERVATION_CHARS] + "\n...[observation truncated]..."


def reset(args: argparse.Namespace) -> None:
    EPISODES_DIR.mkdir(exist_ok=True)
    episode_id = args.episode_id or f"{args.env}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    episode_dir = EPISODES_DIR / episode_id
    if episode_dir.exists():
        shutil.rmtree(episode_dir)
    episode_dir.mkdir(parents=True)

    generated_name = f"_episode_env_{episode_id.replace('-', '_')}"
    generated_path = ROOT / generated_name
    if generated_path.exists():
        shutil.rmtree(generated_path)

    cmd = [
        sys.executable,
        "generate_env.py",
        "--env",
        args.env,
        "--name",
        generated_name,
        "--difficulty",
        args.difficulty,
        "--seed",
        str(args.seed),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stdout + proc.stderr)

    env_dir = episode_dir / "env"
    shutil.move(str(generated_path), str(env_dir))

    state = {
        "episode_id": episode_id,
        "env": args.env,
        "difficulty": args.difficulty,
        "seed": args.seed,
        "step": 0,
        "max_steps": args.max_steps,
        "done": False,
        "reward": 0.0,
        "episode_dir": str(episode_dir),
        "env_dir": str(env_dir),
        "workspace": str(env_dir / "agent" / "workspace"),
        "tools": str(env_dir / "agent" / "tools"),
        "history": [],
        "created_at": time.time(),
    }
    _save_state(state)
    _json(
        {
            "episode_id": episode_id,
            "observation": "Episode initialized. Inspect the workspace and proceed.",
            "reward": 0.0,
            "done": False,
            "info": {
                "env": args.env,
                "difficulty": args.difficulty,
                "seed": args.seed,
                "step": 0,
                "max_steps": args.max_steps,
                "workspace": state["workspace"],
            },
        }
    )


def _run_shell(state: dict[str, Any], cmd: str) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    tools = Path(state["tools"])
    rewritten = cmd.replace("/tools/", str(tools) + "/")
    env = os.environ.copy()
    env["WORKSPACE"] = str(workspace)
    env["PYTHONPATH"] = str(workspace)
    proc = subprocess.run(
        rewritten,
        cwd=workspace,
        shell=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    observation = ""
    if proc.stdout:
        observation += proc.stdout
    if proc.stderr:
        observation += ("\n[stderr]\n" + proc.stderr)
    return observation, {"returncode": proc.returncode, "rewritten_cmd": rewritten}



def _apply_patch(state: dict[str, Any], patch_text: str) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    patch_file = Path(state["episode_dir"]) / f"step_{state['step'] + 1}.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    proc = subprocess.run(
        ["patch", "-p1", "-i", str(patch_file)],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observation = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return observation, {"returncode": proc.returncode, "patch_file": str(patch_file)}


def _submit(state: dict[str, Any]) -> tuple[str, float, bool, dict[str, Any]]:
    """Terminal action.

    If Docker is available, run the generated environment's `run_eval.sh`.
    Otherwise return a clear terminal observation. This keeps the runner usable in
    lightweight CI while still exposing a terminal action for real deployments.
    """
    env_dir = Path(state["env_dir"])
    if shutil.which("docker") is None:
        return (
            "Docker is not available, so the runner cannot execute the full judge locally. "
            "Run the generated environment's ./run_eval.sh on a Docker host for terminal scoring.",
            0.0,
            True,
            {"submit_backend": "unavailable", "reason": "docker_not_found"},
        )
    proc = subprocess.run(["bash", "run_eval.sh"], cwd=env_dir, capture_output=True, text=True, timeout=1800)
    text = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    reward = 1.0 if proc.returncode == 0 else 0.0
    return text, reward, True, {"submit_backend": "docker", "returncode": proc.returncode}


def step(args: argparse.Namespace) -> None:
    state = _load_state(args.episode)
    if state.get("done"):
        _json({"observation": "Episode is already done.", "reward": state.get("reward", 0.0), "done": True, "info": state})
        return

    action = json.loads(args.action)
    action_type = action.get("type") or ("shell" if "cmd" in action else None)
    if not action_type:
        raise SystemExit("Action must contain a type or cmd")

    reward = 0.0
    done = False
    info: dict[str, Any] = {"action_type": action_type}

    try:
        if action_type in {"shell", "run"}:
            observation, extra = _run_shell(state, action["cmd"])
            info.update(extra)
        elif action_type == "read_file":
            path = _safe_join(Path(state["workspace"]), action["path"])
            observation = path.read_text(encoding="utf-8", errors="replace")
        elif action_type == "write_file":
            path = _safe_join(Path(state["workspace"]), action["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action.get("content", ""), encoding="utf-8")
            observation = f"wrote {action['path']}"
            info["written"] = action["path"]
        elif action_type == "list_files":
            root = _safe_join(Path(state["workspace"]), action.get("path", "."))
            observation = "\n".join(str(p.relative_to(Path(state["workspace"]))) for p in sorted(root.rglob("*")) if p.is_file())
        elif action_type == "apply_patch":
            observation, extra = _apply_patch(state, action["patch"])
            info.update(extra)
        elif action_type == "submit":
            observation, reward, done, extra = _submit(state)
            info.update(extra)
        else:
            raise ValueError(f"Unknown action type: {action_type}")
    except Exception as exc:
        observation = f"ERROR: {exc}"
        info["error"] = str(exc)

    state["step"] += 1
    if state["step"] >= state["max_steps"]:
        done = True
        info["terminated_reason"] = "max_steps"
    state["done"] = done
    state["reward"] = reward
    state["history"].append({"step": state["step"], "action": action, "reward": reward, "done": done, "info": info})
    _save_state(state)

    _json(
        {
            "observation": _obs(observation),
            "reward": reward,
            "done": done,
            "info": {
                **info,
                "episode_id": state["episode_id"],
                "step": state["step"],
                "budget_remaining": max(0, state["max_steps"] - state["step"]),
            },
        }
    )


def show_state(args: argparse.Namespace) -> None:
    _json(_load_state(args.episode))


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal gym-like runner for generated eval environments.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--env", default="rope")
    p_reset.add_argument("--difficulty", required=True)
    p_reset.add_argument("--seed", type=int, default=0)
    p_reset.add_argument("--episode-id", default="")
    p_reset.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p_reset.set_defaults(func=reset)

    p_step = sub.add_parser("step")
    p_step.add_argument("--episode", required=True)
    p_step.add_argument("--action", required=True, help="JSON action")
    p_step.set_defaults(func=step)

    p_state = sub.add_parser("state")
    p_state.add_argument("--episode", required=True)
    p_state.set_defaults(func=show_state)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
