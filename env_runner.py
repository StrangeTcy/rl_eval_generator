#!/usr/bin/env python3
"""Minimal gym-like runner for generated evaluation environments."""
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
    return _file_diff(before, after, action["path"]) or f"updated {action['path']}", {"path": action["path"]}


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
        raise ValueError("expected list of replacements")
    results = []
    for r in replacements:
        path = _safe_join(Path(state["workspace"]), r["path"])
        before = path.read_text(encoding="utf-8")
        after = before.replace(r["old"], r["new"])
        path.write_text(after, encoding="utf-8")
        results.append(_file_diff(before, after, r["path"]))
    return "\n".join(results), {"changed_files": [r["path"] for r in replacements]}


def _show_diff(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    original = Path(state["original_workspace"])
    rels = _changed_files(state)
    diffs = []
    for rel in rels:
        before = (original / rel).read_text(encoding="utf-8", errors="replace")
        after = (workspace / rel).read_text(encoding="utf-8", errors="replace")
        diffs.append(f"--- {rel}\n" + _file_diff(before, after, str(rel)))
    return "\n".join(diffs) if diffs else "no changes", {"changed_files": rels}


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


def _progress(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    changed = _changed_files(state)
    required = state.get("required_files") or []
    required_changed = len(set(changed) & set(required))
    score = required_changed / max(len(required), 1)
    details = {"progress_score": round(score, 4), "changed_files": changed, "required_files": required}
    return json.dumps(details, indent=2), details


def _submit(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, float, bool, dict[str, Any]]:
    """Non-interactive submit that judges the current episode workspace."""
    required = set(state.get("required_files") or [])
    changed = set(_changed_files(state))
    missing = sorted(required - changed)
    if missing and not action.get("confirm"):
        return (f"Submit blocked: required files missing: {', '.join(missing)}. Use {{'type':'submit','confirm':true}} to submit anyway.", 0.0, False, {"submit_blocked": True, "missing_required_files": missing})
    
    env_dir = Path(state["env_dir"])
    episode_dir = Path(state["episode_dir"])
    workspace = Path(state["workspace"])
    original = Path(state["original_workspace"])
    
    patch_path = episode_dir / "submission.patch"
    # The judge only accepts edits to patchable files, so the submission patch is
    # restricted to those. This also avoids including stray workspace artifacts
    # (e.g. patch(1) .orig backups, scratch files) that the agent may have left.
    patchable = set(state.get("patchable_files") or [])
    changed_rels = [r for r in sorted(_changed_files(state)) if not patchable or r in patchable]

    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    diffs = []
    for rel in changed_rels:
        before = _read(original / rel)
        after = _read(workspace / rel)
        # Emit git-style a/ b/ headers so the judge's patch_validator (which
        # strips a single a//b/ prefix and applies with `patch -p1`) accepts it.
        diff = "\n".join(difflib.unified_diff(
            before.splitlines(), after.splitlines(),
            fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
        if diff:
            diffs.append(diff)
    patch_path.write_text("\n".join(diffs) + ("\n" if diffs else ""), encoding="utf-8")
    
    judge_workdir = episode_dir / "judge_runtime"
    if judge_workdir.exists():
        shutil.rmtree(judge_workdir)
    judge_workdir.mkdir(parents=True)
    
    shutil.copytree(original, judge_workdir / "originals")
    sub_dir = judge_workdir / "submission"
    sub_dir.mkdir(parents=True)
    shutil.copy2(patch_path, sub_dir / "agent.patch")
    
    judge_script = env_dir / "judge" / "judge.py"
    judge_env = os.environ.copy()
    judge_env["JUDGE_SEED"] = str(state["seed"])
    judge_env["PYTHONPATH"] = str(env_dir / "judge")
    # The judge and validators read these paths (defaulting to the Docker mount
    # points). Point them at the local episode submission so the runner can grade
    # the current workspace non-interactively, without invoking run_eval.sh.
    judge_env["JUDGE_PATCH_PATH"] = str(sub_dir / "agent.patch")
    judge_env["JUDGE_ORIGINALS_DIR"] = str(judge_workdir / "originals")
    
    # The judge trains a model; its internal step timeouts can reach ~1800s
    # (e.g. BatchNorm/ResNet). The wrapper budget must exceed those so the
    # runner does not kill a legitimate judge run before it finishes. Override
    # with JUDGE_SUBMIT_TIMEOUT or per-call action {"timeout": <seconds>}.
    judge_timeout = int(action.get("timeout") or os.environ.get("JUDGE_SUBMIT_TIMEOUT", "2100"))
    try:
        cmd = [sys.executable, str(judge_script)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=judge_timeout, env=judge_env)
        
        if proc.returncode != 0 and not proc.stdout:
            return (f"Judge execution failed:\n{proc.stderr}", 0.0, True, {"returncode": proc.returncode})
        
        try:
            result_json = json.loads(proc.stdout.strip().splitlines()[-1])
            return (json.dumps(result_json, indent=2), result_json.get("score", 0.0), True, result_json)
        except Exception:
            return (proc.stdout or proc.stderr, 0.0, True, {"error": "could not parse judge output"})

    except Exception as exc:
        return (f"Submission error: {exc}", 0.0, True, {"error": str(exc)})


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
            observation = _file_diff(before, action.get("content", ""), action["path"]) or f"updated {action['path']}"
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
    parser = argparse.ArgumentParser(description="Minimal gym-like runner for generated evaluation environments.")
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
