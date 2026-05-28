#!/usr/bin/env python3
"""Minimal reset/step runner for generated evaluation environments."""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
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


def _parse_list_literal_from_file(path: Path, var_name: str) -> list[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(rf"^{re.escape(var_name)}\s*=\s*(\[[^\n]*\])", text, re.M)
    if not match:
        return []
    try:
        value = json.loads(match.group(1).replace("'", '"'))
    except Exception:
        return []
    return value if isinstance(value, list) else []


def _parse_required_files(judge_path: Path) -> list[str]:
    if not judge_path.is_file():
        return []
    text = judge_path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"require_changed_files\(result,\s*\{([^}]+)\}\)", text)
    required: set[str] = set()
    for body in matches:
        required.update(re.findall(r"['\"]([^'\"]+)['\"]", body))
    return sorted(required)


def _changed_files(state: dict[str, Any]) -> list[str]:
    workspace = Path(state["workspace"])
    original = Path(state["original_workspace"])
    current_files = {p.relative_to(workspace) for p in workspace.rglob("*") if p.is_file()}
    original_files = {p.relative_to(original) for p in original.rglob("*") if p.is_file()}
    changed: list[str] = []
    for rel in sorted(current_files | original_files):
        cur = workspace / rel
        old = original / rel
        if not cur.exists() or not old.exists() or cur.read_bytes() != old.read_bytes():
            changed.append(str(rel))
    return changed


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

    cmd = [sys.executable, "generate_env.py", "--env", args.env, "--name", generated_name, "--difficulty", args.difficulty, "--seed", str(args.seed)]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stdout + proc.stderr)

    env_dir = episode_dir / "env"
    shutil.move(str(generated_path), str(env_dir))
    workspace = env_dir / "agent" / "workspace"
    original_workspace = episode_dir / "original_workspace"
    shutil.copytree(workspace, original_workspace)

    patchable_files = _parse_list_literal_from_file(env_dir / "judge" / "source_validator.py", "PATCHABLE")
    required_files = _parse_required_files(env_dir / "judge" / "judge.py")

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
        "workspace": str(workspace),
        "original_workspace": str(original_workspace),
        "tools": str(env_dir / "agent" / "tools"),
        "patchable_files": patchable_files,
        "required_files": required_files,
        "history": [],
        "created_at": time.time(),
    }
    _save_state(state)
    _json({
        "episode_id": episode_id,
        "observation": "Episode initialized. Inspect the workspace and proceed.",
        "reward": 0.0,
        "done": False,
        "info": {"env": args.env, "difficulty": args.difficulty, "seed": args.seed, "step": 0, "max_steps": args.max_steps, "workspace": str(workspace), "patchable_files": patchable_files, "required_files": required_files},
    })


def _run_shell(state: dict[str, Any], cmd: str) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    tools = Path(state["tools"])
    rewritten = cmd.replace("/tools/", str(tools) + "/")
    env = os.environ.copy()
    env["WORKSPACE"] = str(workspace)
    env["PYTHONPATH"] = str(workspace)
    proc = subprocess.run(rewritten, cwd=workspace, shell=True, capture_output=True, text=True, timeout=120, env=env)
    observation = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return observation, {"returncode": proc.returncode, "rewritten_cmd": rewritten}


def _file_diff(before: str, after: str, path: str) -> str:
    return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile=f"before/{path}", tofile=f"after/{path}", lineterm=""))


def _read_file(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    path = _safe_join(Path(state["workspace"]), action["path"])
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(int(action.get("start", 1)), 1)
    end = min(int(action.get("end", len(lines))), len(lines))
    selected = lines[start - 1:end]
    if action.get("line_numbers") or action.get("numbered") or action.get("type") == "view_file":
        width = len(str(max(end, 1)))
        text = "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(selected, start))
    else:
        text = "\n".join(selected)
    return text + ("\n" if text else ""), {"path": action["path"], "start": start, "end": end}


def _replace_text(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    path = _safe_join(Path(state["workspace"]), action["path"])
    old = action["old"]
    new = action["new"]
    before = path.read_text(encoding="utf-8")
    count = before.count(old)
    if count == 0:
        raise ValueError("old text not found")
    if count > 1 and not action.get("all") and "occurrence" not in action:
        raise ValueError(f"old text occurs {count} times; specify occurrence or all=true")
    if action.get("all"):
        after = before.replace(old, new)
    elif "occurrence" in action:
        occurrence = int(action["occurrence"])
        parts = before.split(old)
        if occurrence < 1 or occurrence >= len(parts):
            raise ValueError(f"occurrence must be between 1 and {count}")
        after = old.join(parts[:occurrence]) + new + old.join(parts[occurrence:])
    else:
        after = before.replace(old, new, 1)
    path.write_text(after, encoding="utf-8")
    return _file_diff(before, after, action["path"]) or f"updated {action['path']}", {"path": action["path"], "occurrences": count}


def _replace_lines(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    path = _safe_join(Path(state["workspace"]), action["path"])
    before = path.read_text(encoding="utf-8")
    lines = before.splitlines()
    start = int(action["start_line"])
    end = int(action["end_line"])
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"invalid line range {start}:{end}")
    lines[start - 1:end] = action.get("content", "").splitlines()
    after = "\n".join(lines) + "\n"
    path.write_text(after, encoding="utf-8")
    return _file_diff(before, after, action["path"]), {"path": action["path"], "start_line": start, "end_line": end}


def _replace_block(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    path = _safe_join(Path(state["workspace"]), action["path"])
    before = path.read_text(encoding="utf-8")
    start = before.find(action["start"])
    if start == -1:
        raise ValueError("start marker not found")
    end = before.find(action["end"], start + len(action["start"]))
    if end == -1:
        raise ValueError("end marker not found")
    after = before[:start] + action.get("content", "") + before[end:]
    path.write_text(after, encoding="utf-8")
    return _file_diff(before, after, action["path"]), {"path": action["path"]}


def _apply_patch(state: dict[str, Any], patch_text: str) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    patch_file = Path(state["episode_dir"]) / f"step_{state['step'] + 1}.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    proc = subprocess.run(["patch", "-p1", "-i", str(patch_file)], cwd=workspace, capture_output=True, text=True, timeout=30)
    observation = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return observation, {"returncode": proc.returncode, "patch_file": str(patch_file)}


def _apply_structured_edit(state: dict[str, Any], edit_text: str) -> tuple[str, dict[str, Any]]:
    spec = json.loads(edit_text)
    replacements = spec.get("replace") or spec.get("replacements")
    if not isinstance(replacements, list):
        raise ValueError("structured edit must contain a replace list")
    outputs = []
    changed = []
    for item in replacements:
        action = {"path": item.get("path") or item.get("name"), "start_line": item["start_line"], "end_line": item["end_line"], "content": item.get("content", item.get("replace_content", ""))}
        out, _ = _replace_lines(state, action)
        outputs.append(out)
        changed.append(action["path"])
    return "\n".join(outputs), {"returncode": 0, "structured_edit": True, "changed": changed}


def _show_diff(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    original = Path(state["original_workspace"])
    rels = {p.relative_to(workspace) for p in workspace.rglob("*") if p.is_file()} | {p.relative_to(original) for p in original.rglob("*") if p.is_file()}
    chunks = []
    for rel in sorted(rels):
        cur = workspace / rel
        old = original / rel
        before = old.read_text(encoding="utf-8", errors="replace") if old.exists() else ""
        after = cur.read_text(encoding="utf-8", errors="replace") if cur.exists() else ""
        if before != after:
            chunks.append(_file_diff(before, after, str(rel)))
    return "\n".join(chunks) if chunks else "no changes", {"changed_files": _changed_files(state)}


def _search(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    root = _safe_join(workspace, action.get("path", "."))
    regex = re.compile(action["pattern"])
    matches = []
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    for path in files:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append(f"{path.relative_to(workspace)}:{i}: {line}")
    return "\n".join(matches) if matches else "no matches", {"matches": len(matches)}


def _score_rope_progress(state: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    workspace = Path(state["workspace"])
    changed = set(_changed_files(state))
    rope = (workspace / "rope.py").read_text(encoding="utf-8", errors="replace") if (workspace / "rope.py").exists() else ""
    attention = (workspace / "attention.py").read_text(encoding="utf-8", errors="replace") if (workspace / "attention.py").exists() else ""
    cache = (workspace / "cache.py").read_text(encoding="utf-8", errors="replace") if (workspace / "cache.py").exists() else ""
    checks = {
        "changed_rope": "rope.py" in changed,
        "changed_attention": "attention.py" in changed,
        "changed_cache": "cache.py" in changed,
        "rope_uses_offset": "torch.arange(offset, offset + seq_len" in rope,
        "rope_even_odd_rotation": "0::2" in rope and "1::2" in rope and "torch.cat((-x2, x1)" not in rope,
        "rope_frequency_scaling": "/ dim))" in rope and "dim // 2" not in rope,
        "cache_returns_tokens_seen": "return self.tokens_seen" in cache,
        "cache_advances": "self.tokens_seen += chunk_len" in cache,
        "attention_uses_cache_offset": "cache.position_offset()" in attention,
    }
    weights = {
        "changed_rope": 0.05,
        "changed_attention": 0.05,
        "changed_cache": 0.05,
        "rope_uses_offset": 0.15,
        "rope_even_odd_rotation": 0.20,
        "rope_frequency_scaling": 0.15,
        "cache_returns_tokens_seen": 0.10,
        "cache_advances": 0.10,
        "attention_uses_cache_offset": 0.15,
    }
    score = sum(weights[k] for k, v in checks.items() if v)
    return round(score, 4), {"checks": checks, "changed_files": sorted(changed)}


def _progress(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if state.get("env") == "rope":
        score, details = _score_rope_progress(state)
        return json.dumps({"progress_score": score, **details}, indent=2), {"progress_score": score, **details}
    changed = _changed_files(state)
    required = state.get("required_files") or []
    required_changed = len(set(changed) & set(required))
    score = required_changed / max(len(required), 1)
    details = {"progress_score": round(score, 4), "changed_files": changed, "required_files": required}
    return json.dumps(details, indent=2), details


def _submit(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, float, bool, dict[str, Any]]:
    required = set(state.get("required_files") or [])
    missing = sorted(required - set(_changed_files(state)))
    if missing and not action.get("confirm"):
        return ("Submit blocked: required files have not been modified: " + ", ".join(missing) + ". Use {\"type\":\"submit\",\"confirm\":true} to submit anyway.", 0.0, False, {"submit_blocked": True, "missing_required_files": missing})
    env_dir = Path(state["env_dir"])
    if shutil.which("docker") is None:
        _text, progress_info = _progress(state)
        reward = float(progress_info.get("progress_score", 0.0))
        return ("Docker is not available, so the runner cannot execute the full judge locally. "
                "Returning structural progress reward instead. Run the generated environment's ./run_eval.sh on a Docker host for terminal scoring.",
                reward,
                True,
                {"submit_backend": "unavailable", "reason": "docker_not_found", **progress_info})
    proc = subprocess.run(["bash", "run_eval.sh"], cwd=env_dir, capture_output=True, text=True, timeout=1800)
    text = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return text, 1.0 if proc.returncode == 0 else 0.0, True, {"submit_backend": "docker", "returncode": proc.returncode}


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
        elif action_type in {"read_file", "view_file"}:
            observation, extra = _read_file(state, action)
        elif action_type == "write_file":
            path = _safe_join(Path(state["workspace"]), action["path"])
            before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action.get("content", ""), encoding="utf-8")
            observation = _file_diff(before, action.get("content", ""), action["path"]) or f"wrote {action['path']}"
            extra = {"written": action["path"]}
        elif action_type == "list_files":
            root = _safe_join(Path(state["workspace"]), action.get("path", "."))
            observation = "\n".join(str(p.relative_to(Path(state["workspace"]))) for p in sorted(root.rglob("*")) if p.is_file())
            extra = {}
        elif action_type == "search":
            observation, extra = _search(state, action)
        elif action_type == "replace_text":
            observation, extra = _replace_text(state, action)
        elif action_type == "replace_lines":
            observation, extra = _replace_lines(state, action)
        elif action_type == "replace_block":
            observation, extra = _replace_block(state, action)
        elif action_type == "show_diff":
            observation, extra = _show_diff(state)
        elif action_type == "changed_files":
            changed = _changed_files(state)
            required = state.get("required_files") or []
            missing = sorted(set(required) - set(changed))
            observation = json.dumps({"changed": changed, "required": required, "missing_required": missing}, indent=2)
            extra = {"changed_files": changed, "missing_required_files": missing}
        elif action_type == "progress":
            observation, extra = _progress(state)
        elif action_type == "apply_patch":
            observation, extra = _apply_patch(state, action["patch"])
        elif action_type == "apply_patch_base64":
            patch_text = base64.b64decode(action["patch_base64"]).decode("utf-8")
            if patch_text.lstrip().startswith("{"):
                observation, extra = _apply_structured_edit(state, patch_text)
            else:
                observation, extra = _apply_patch(state, patch_text)
        elif action_type == "submit":
            observation, reward, done, extra = _submit(state, action)
        else:
            raise ValueError(f"Unknown action type: {action_type}")
        info.update(extra)
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
    _json({"observation": _obs(observation), "reward": reward, "done": done, "info": {**info, "episode_id": state["episode_id"], "step": state["step"], "budget_remaining": max(0, state["max_steps"] - state["step"])}})


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
