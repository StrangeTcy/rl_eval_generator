#!/usr/bin/env python3
"""Minimal stateful runner for generated evaluation environments.

The runner is intentionally repository-specific and does not depend on Gym.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from arena.diffing import files_differ, has_symlink_in_path, text_for_diff, unified_text_diff
from arena.docker_backend import DockerBackend, DockerBackendError
from arena.episode_id import validate_episode_id

ROOT = Path(__file__).resolve().parent
EPISODES_DIR = ROOT / ".episodes"
DEFAULT_MAX_STEPS = 40
MAX_OBSERVATION_CHARS = 12000
MAX_SUBMISSION_SOURCE_BYTES = 2 * 1024 * 1024


def _json(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, indent=2))


def _safe_join(root: Path, rel: str) -> Path:
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace: {rel}") from exc
    return candidate


def _episode_dir(episode_id: str) -> Path:
    """Never let an external episode ID escape the runner's data directory."""
    return EPISODES_DIR / validate_episode_id(episode_id)


def _load_state(episode_id: str) -> dict[str, Any]:
    path = _episode_dir(episode_id) / "state.json"
    if not path.is_file():
        raise SystemExit(f"Unknown episode: {episode_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(state: dict[str, Any]) -> None:
    path = _episode_dir(state["episode_id"]) / "state.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _event_path(state_or_dir: dict[str, Any] | Path) -> Path:
    if isinstance(state_or_dir, Path):
        episode_dir = state_or_dir
    else:
        episode_dir = Path(state_or_dir["episode_dir"])
    return episode_dir / "environment-events.jsonl"


def _write_event(state_or_dir: dict[str, Any] | Path, event: dict[str, Any]) -> None:
    path = _event_path(state_or_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


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
    # Do not dereference workspace symlinks here: the agent can create them,
    # and these paths are later shown in observations and public artifacts.
    current_files = {p.relative_to(workspace) for p in workspace.rglob("*") if p.is_file() or p.is_symlink()}
    original_files = {p.relative_to(original) for p in original.rglob("*") if p.is_file() or p.is_symlink()}
    changed: list[str] = []
    for rel in sorted(current_files | original_files):
        cur = workspace / rel
        old = original / rel
        if (
            has_symlink_in_path(workspace, rel) or has_symlink_in_path(original, rel)
            or not cur.is_file() or not old.is_file()
            or files_differ(cur, old)
        ):
            changed.append(str(rel))
    return changed


def reset(args: argparse.Namespace) -> None:
    sandbox = getattr(args, "sandbox", "local")
    keep_images = bool(getattr(args, "keep_images", False))
    keep_workspace = bool(getattr(args, "keep_workspace", False))
    episode_id = args.episode_id or f"{args.env}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    episode_dir = _episode_dir(episode_id)
    EPISODES_DIR.mkdir(exist_ok=True)
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
    workspace = env_dir / "agent" / "workspace"
    original_workspace = episode_dir / "original_workspace"
    shutil.copytree(workspace, original_workspace)

    patchable_files = _parse_list_literal_from_file(env_dir / "judge" / "source_validator.py", "PATCHABLE")
    required_files = _parse_required_files(env_dir / "judge" / "judge.py")
    agent_image: dict[str, Any] | None = None
    judge_image: dict[str, Any] | None = None
    if sandbox == "docker":
        try:
            backend = DockerBackend()
            agent, judge = backend.build_environment(env_dir, episode_id)
            agent_image = agent.as_dict()
            judge_image = judge.as_dict()
        except DockerBackendError as exc:
            shutil.rmtree(episode_dir, ignore_errors=True)
            raise SystemExit(f"Docker sandbox setup failed: {exc}") from exc

    state = {
        "episode_id": episode_id,
        "env": args.env,
        "difficulty": args.difficulty,
        "seed": args.seed,
        "step": 0,
        "max_steps": args.max_steps,
        "done": False,
        "reward": 0.0,
        "sandbox": sandbox,
        "episode_dir": str(episode_dir),
        "env_dir": str(env_dir),
        "workspace": str(workspace),
        "original_workspace": str(original_workspace),
        "tools": str(env_dir / "agent" / "tools"),
        "patchable_files": patchable_files,
        "required_files": required_files,
        "agent_image": agent_image,
        "judge_image": judge_image,
        "agent_image_id": (agent_image or {}).get("id"),
        "judge_image_id": (judge_image or {}).get("id"),
        "agent_image_digest": (agent_image or {}).get("digest"),
        "judge_image_digest": (judge_image or {}).get("digest"),
        "keep_images": keep_images,
        "keep_workspace": keep_workspace,
        "history": [],
        "created_at": time.time(),
    }
    _save_state(state)
    _write_event(
        episode_dir,
        {
            "ts": time.time(),
            "event": "reset",
            "episode_id": episode_id,
            "env": args.env,
            "difficulty": args.difficulty,
            "seed": args.seed,
            "sandbox": sandbox,
            "agent_image": agent_image,
            "judge_image": judge_image,
        },
    )
    _json({
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
            "workspace": str(workspace),
            "episode_dir": str(episode_dir),
            "sandbox": sandbox,
            "patchable_files": patchable_files,
            "required_files": required_files,
            "agent_image": agent_image,
            "judge_image": judge_image,
            "agent_image_id": (agent_image or {}).get("id"),
            "judge_image_id": (judge_image or {}).get("id"),
            "agent_image_digest": (agent_image or {}).get("digest"),
            "judge_image_digest": (judge_image or {}).get("digest"),
        },
    })


def _run_shell(state: dict[str, Any], cmd: str) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    tools = Path(state["tools"])
    if state.get("sandbox") == "docker":
        image_info = state.get("agent_image") or {}
        image = image_info.get("name") or state.get("agent_image_name")
        if not image:
            return "Docker agent image is missing", {"infrastructure_failure": "agent_image_missing"}
        result = DockerBackend().run_agent(image, workspace, tools, cmd)
        observation = (result.stdout or "") + ("\n[stderr]\n" + result.stderr if result.stderr else "")
        extra = {
            "returncode": result.returncode,
            "sandbox": "docker",
            "container_command": result.command,
        }
        if result.backend_error:
            extra["infrastructure_failure"] = "agent_container_error"
        return observation, extra

    rewritten = cmd.replace("/tools/", str(tools) + "/")
    env = os.environ.copy()
    for name in list(env):
        upper = name.upper()
        if upper in {"OPENROUTER_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "API_KEY"} or "API_KEY" in upper or upper.endswith("_TOKEN"):
            env.pop(name, None)
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
    observation = (proc.stdout or "") + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    return observation, {"returncode": proc.returncode, "rewritten_cmd": rewritten, "sandbox": "local"}


def _file_diff(before: str, after: str, path: str) -> str:
    return unified_text_diff(before, after, fromfile=f"before/{path}", tofile=f"after/{path}").rstrip("\n")


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
        old, cur = original / rel, workspace / rel
        if has_symlink_in_path(original, rel) or has_symlink_in_path(workspace, rel):
            diffs.append(f"--- {rel}\n[symlink contents omitted]")
            continue
        before = text_for_diff(old)
        after = text_for_diff(cur)
        diff = _file_diff(before, after, str(rel))
        diffs.append(f"--- {rel}\n" + (diff or "[changed contents omitted]"))
    return "\n".join(diffs) if diffs else "no changes", {"changed_files": rels}


def _search(state: dict[str, Any], action: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    workspace = Path(state["workspace"])
    root = _safe_join(workspace, action.get("path", "."))
    regex = re.compile(action["pattern"])
    matches = []
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
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


def _extract_last_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped:
        try:
            value = json.loads(stripped)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        return None
    scored = [item for item in candidates if "verdict" in item or "score" in item]
    return max(scored or candidates, key=lambda item: len(json.dumps(item)))


def _make_submission_patch(state: dict[str, Any]) -> tuple[Path, list[str]]:
    """Create a git-style patch from the persistent workspace."""
    episode_dir = Path(state["episode_dir"])
    workspace = Path(state["workspace"])
    original = Path(state["original_workspace"])
    patch_path = episode_dir / "submission.patch"
    patchable = set(state.get("patchable_files") or [])
    changed_rels = [
        rel for rel in sorted(_changed_files(state)) if not patchable or rel in patchable
    ]

    def _read(root: Path, rel: str) -> str:
        if has_symlink_in_path(root, rel):
            raise ValueError(f"Patchable file is a symlink: {rel}")
        path = root / rel
        if not path.is_file():
            return ""
        if path.stat().st_size > MAX_SUBMISSION_SOURCE_BYTES:
            raise ValueError(f"Patchable source file is too large: {rel}")
        try:
            return path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Patchable file is not UTF-8: {rel}") from exc

    diffs: list[str] = []
    for rel in changed_rels:
        before = _read(original, rel)
        after = _read(workspace, rel)
        if (original / rel).is_file() and not (workspace / rel).is_file():
            raise ValueError(f"Patchable file was deleted: {rel}")
        diff = unified_text_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}")
        if diff:
            diffs.append(diff)
    patch_path.write_text("".join(diffs), encoding="utf-8")
    return patch_path, changed_rels


def _submission_failure(mode: str, note: str, **details: Any) -> tuple[str, float, bool, dict[str, Any]]:
    result = {"verdict": "FAIL", "score": 0.0, "failure_mode": mode, "notes": [note]}
    return json.dumps(result, indent=2), 0.0, True, {"judge_result": result, **details}


def _judge_result(stdout: str, stderr: str, returncode: int) -> dict[str, Any]:
    """Accept only a complete judge verdict with the expected exit status."""
    result = _extract_last_json_object(stdout)
    if result is not None:
        verdict = result.get("verdict")
        score = result.get("score")
        if (
            verdict in {"PASS", "FAIL"}
            and isinstance(score, (int, float)) and not isinstance(score, bool)
            and math.isfinite(score) and 0 <= score <= 1
            and verdict == ("PASS" if score >= 1 else "FAIL")
            and returncode == (0 if verdict == "PASS" else 1)
            and isinstance(result.get("failure_mode"), str)
            and result["failure_mode"] not in {"unknown", ""}
            and (result["failure_mode"] == "pass") == (verdict == "PASS")
        ):
            return result
    reason = f"Judge exited {returncode} without a valid JSON verdict"
    return {
        "verdict": "FAIL", "score": 0.0, "failure_mode": "judge_runtime_error",
        "notes": [reason, stderr[-2000:]],
    }


def _submit(
    state: dict[str, Any], action: dict[str, Any], *, judge_timeout: int | None = None
) -> tuple[str, float, bool, dict[str, Any]]:
    """Submit to the judge; only the host can set its timeout, not the model."""
    required = set(state.get("required_files") or [])
    changed = set(_changed_files(state))
    missing = sorted(required - changed)
    if missing and not action.get("confirm"):
        return (
            f"Submit blocked: required files missing: {', '.join(missing)}. Use "
            "{'type':'submit','confirm':true} to submit anyway.",
            0.0,
            False,
            {"submit_blocked": True, "missing_required_files": missing},
        )

    env_dir = Path(state["env_dir"])
    episode_dir = Path(state["episode_dir"])
    try:
        patch_path, _ = _make_submission_patch(state)
    except ValueError as exc:
        return _submission_failure("patch_invalid", str(exc))

    if state.get("sandbox") == "docker":
        image_info = state.get("judge_image") or {}
        image = image_info.get("name") or state.get("judge_image_name")
        if not image:
            return _submission_failure("judge_runtime_error", "Docker judge image is missing from episode state")
        submission_dir = episode_dir / "submission"
        submission_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(patch_path, submission_dir / "agent.patch")
        try:
            backend = DockerBackend()
            container = backend.run_judge(image, submission_dir, int(state["seed"]))
        except DockerBackendError as exc:
            (episode_dir / "judge.stderr").write_text(str(exc), encoding="utf-8")
            return _submission_failure("judge_runtime_error", f"Docker judge failed to run: {exc}")
        (episode_dir / "judge.stdout").write_text(container.stdout, encoding="utf-8")
        (episode_dir / "judge.stderr").write_text(container.stderr, encoding="utf-8")
        result_json = _judge_result(container.stdout, container.stderr, container.returncode)
        info: dict[str, Any] = {
            "sandbox": "docker",
            "returncode": container.returncode,
            "judge_result": result_json,
            "judge_stdout": container.stdout,
            "judge_stderr": container.stderr,
            "submission_dir": str(submission_dir),
        }
        if not state.get("keep_images"):
            try:
                removed = backend.remove_images(
                    (state.get("agent_image") or {}).get("name"),
                    image,
                )
            except DockerBackendError:
                removed = []
            state["images_removed"] = removed
        return (
            json.dumps(result_json, indent=2),
            float(result_json.get("score", 0.0)),
            True,
            info,
        )

    # Local mode retains the original runner behavior for compatibility and
    # testing, but uses the same patch and final-result parsing as Docker mode.
    judge_workdir = episode_dir / "judge_runtime"
    if judge_workdir.exists():
        shutil.rmtree(judge_workdir)
    judge_workdir.mkdir(parents=True)
    shutil.copytree(Path(state["original_workspace"]), judge_workdir / "originals")
    sub_dir = judge_workdir / "submission"
    sub_dir.mkdir(parents=True)
    shutil.copy2(patch_path, sub_dir / "agent.patch")

    judge_script = env_dir / "judge" / "judge.py"
    judge_env = os.environ.copy()
    for name in list(judge_env):
        upper = name.upper()
        if upper in {"OPENROUTER_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "API_KEY"} or "API_KEY" in upper or upper.endswith("_TOKEN"):
            judge_env.pop(name, None)
    judge_env["JUDGE_SEED"] = str(state["seed"])
    judge_env["PYTHONPATH"] = str(env_dir / "judge")
    judge_env["JUDGE_PATCH_PATH"] = str(sub_dir / "agent.patch")
    judge_env["JUDGE_ORIGINALS_DIR"] = str(judge_workdir / "originals")
    timeout = judge_timeout if judge_timeout is not None else int(os.environ.get("JUDGE_SUBMIT_TIMEOUT", "2100"))
    try:
        proc = subprocess.run(
            [sys.executable, str(judge_script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=judge_env,
        )
        (episode_dir / "judge.stdout").write_text(proc.stdout or "", encoding="utf-8")
        (episode_dir / "judge.stderr").write_text(proc.stderr or "", encoding="utf-8")
        result_json = _judge_result(proc.stdout or "", proc.stderr or "", proc.returncode)
        return (
            json.dumps(result_json, indent=2),
            float(result_json.get("score", 0.0)),
            True,
            {
                "sandbox": "local",
                "returncode": proc.returncode,
                "judge_result": result_json,
                "judge_stdout": proc.stdout or "",
                "judge_stderr": proc.stderr or "",
            },
        )
    except Exception as exc:
        (episode_dir / "judge.stderr").write_text(str(exc), encoding="utf-8")
        return _submission_failure("judge_runtime_error", f"Judge process failed: {exc}")


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
        if extra.get("infrastructure_failure"):
            done = True
    except Exception as exc:
        observation = f"ERROR: {exc}"
        info["error"] = str(exc)
        if action_type == "submit":
            observation, reward, done, failure = _submission_failure(
                "controller_error", f"Runner could not submit: {exc}"
            )
            info.update(failure)
    state["step"] += 1
    if state["step"] >= state["max_steps"]:
        done = True
        info["terminated_reason"] = "max_steps"
    state["done"] = done
    state["reward"] = reward
    state["history"].append({"step": state["step"], "action": action, "reward": reward, "done": done, "info": info})
    _save_state(state)
    _write_event(
        state,
        {
            "ts": time.time(),
            "event": "step",
            "step": state["step"],
            "action": action,
            "observation": _obs(observation),
            "reward": reward,
            "done": done,
            "info": info,
        },
    )
    _json({"observation": _obs(observation), "reward": reward, "done": done, "info": {**info, "episode_id": state["episode_id"], "step": state["step"], "budget_remaining": max(0, state["max_steps"] - state["step"])}})


def submit_episode(args: argparse.Namespace) -> None:
    """Submit even if the interaction budget has already been exhausted."""
    state = _load_state(args.episode)
    try:
        observation, reward, done, info = _submit(state, {"confirm": args.confirm}, judge_timeout=args.timeout)
    except Exception as exc:
        observation, reward, done, info = _submission_failure(
            "controller_error", f"Runner could not submit: {exc}"
        )
    state["done"] = done
    state["reward"] = reward
    state["submitted"] = True
    state["submission_info"] = info
    _save_state(state)
    _write_event(
        state,
        {
            "ts": time.time(),
            "event": "submit",
            "step": state["step"],
            "reward": reward,
            "done": done,
            "info": info,
        },
    )
    _json({
        "observation": _obs(observation),
        "reward": reward,
        "done": done,
        "info": {**info, "episode_id": state["episode_id"], "step": state["step"]},
    })


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
    p_reset.add_argument("--sandbox", choices=("local", "docker"), default="local")
    p_reset.add_argument("--keep-images", action="store_true")
    p_reset.add_argument("--keep-workspace", action="store_true")
    p_reset.set_defaults(func=reset)
    p_step = sub.add_parser("step")
    p_step.add_argument("--episode", required=True)
    p_step.add_argument("--action", required=True, help="JSON action")
    p_step.set_defaults(func=step)
    p_submit = sub.add_parser("submit")
    p_submit.add_argument("--episode", required=True)
    p_submit.add_argument("--confirm", action="store_true")
    p_submit.add_argument("--timeout", type=int, default=2100)
    p_submit.set_defaults(func=submit_episode)
    p_state = sub.add_parser("state")
    p_state.add_argument("--episode", required=True)
    p_state.set_defaults(func=show_state)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
