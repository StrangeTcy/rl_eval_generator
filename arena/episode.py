"""Host-side model loop for non-interactive arena episodes."""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifacts import RunArtifacts, manifest_defaults, utc_now
from .docker_backend import DockerBackend
from .providers import (
    Completion,
    ProviderClient,
    ProviderError,
    provider_metadata,
    resolve_api_base,
    resolve_credentials,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_OBS_CHARS = 12000
MAX_HISTORY_CHARS = 28000

SYSTEM_PROMPT = """You are an autonomous coding agent controlling a stateful evaluation environment.

You must respond with exactly one JSON object and nothing else.

Allowed actions:
- {"cmd": "shell command"}
- {"type": "read_file", "path": "relative/path"}
- {"type": "write_file", "path": "relative/path", "content": "..."}
- {"type": "apply_patch", "patch": "unified diff"}
- {"type": "apply_patch_base64", "patch_base64": "base64-encoded unified diff"}
- {"type": "list_files", "path": "."}
- {"type": "search", "pattern": "regular expression", "path": "."}
- {"type": "show_diff"}
- {"type": "changed_files"}
- {"type": "submit", "confirm": true}

Do not use Markdown. Do not explain. Return only the action JSON.
For code edits, prefer a small unified diff via apply_patch. Use apply_patch_base64 only for a base64-encoded unified diff; never encode JSON edit instructions as patch_base64.
The current working directory for shell commands is the environment workspace.
"""


@dataclass
class EpisodeOptions:
    provider: str
    model: str
    env: str
    difficulty: str
    seed: int = 0
    max_steps: int = 30
    max_tokens: int = 1024
    temperature: float = 0.0
    request_extra: dict[str, Any] = field(default_factory=dict)
    sandbox: str = "docker"
    out: Path = Path("runs")
    api_key: str | None = None
    api_key_env: str | None = None
    api_base: str | None = None
    invalid_retries: int = 2
    episode_id: str | None = None
    keep_images: bool = False
    keep_workspace: bool = False


def clip(text: str, limit: int = MAX_OBS_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def parse_action(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse the deliberately small JSON action protocol."""

    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, re.S)
    if match and match.group(0) != raw:
        candidates.append(match.group(0))
    for candidate in candidates:
        parsed: Any = None
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                continue
        if not isinstance(parsed, dict):
            continue
        if isinstance(parsed.get("action"), dict):
            parsed = parsed["action"]
        if "type" in parsed or "cmd" in parsed:
            return parsed, None
        return None, "JSON object must contain either 'type' or 'cmd'"
    if '"type"' in raw and '"write_file"' in raw:
        return None, "Could not parse write_file JSON; escape newlines and quotes."
    if '"type"' in raw and '"apply_patch"' in raw:
        return None, "Could not parse patch JSON; use apply_patch_base64 for multiline diffs."
    return None, "Could not parse a valid JSON action"


def format_messages(
    history: list[dict[str, str]], observation: str, invalid_note: str | None = None
) -> list[dict[str, str]]:
    user = "Current observation:\n" + clip(observation)
    if invalid_note:
        user += (
            "\n\nYour previous response was invalid: "
            + invalid_note
            + "\nReturn exactly one valid JSON action."
        )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user})
    while sum(len(str(message.get("content", ""))) for message in messages) > MAX_HISTORY_CHARS and len(messages) > 3:
        del messages[1]
    return messages


def _controller_environment() -> dict[str, str]:
    """Run environment subprocesses without provider credentials."""

    env = os.environ.copy()
    for name in list(env):
        upper = name.upper()
        if upper in {
            "OPENROUTER_API_KEY",
            "HF_TOKEN",
            "HUGGINGFACEHUB_API_TOKEN",
            "API_KEY",
        } or "API_KEY" in upper or upper.endswith("_TOKEN"):
            env.pop(name, None)
    return env


def _run_env_runner(arguments: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "env_runner.py"), *arguments],
        cwd=ROOT,
        env=_controller_environment(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # env_runner does not include secrets in its errors, but sanitize this
        # boundary anyway because commands are often run from shell wrappers.
        raise RuntimeError((proc.stdout + proc.stderr)[-8000:])
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("env_runner returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("env_runner returned a non-object JSON value")
    return data


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract the outer judge result from stdout with optional log lines."""

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
    # Nested check/metric objects can also be valid JSON.  The top-level judge
    # object is the candidate carrying the verdict or score and is normally the
    # largest such object.
    scored = [item for item in candidates if "verdict" in item or "score" in item]
    return max(scored or candidates, key=lambda item: len(json.dumps(item)))


def _request_extra(value: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("--request-extra must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--request-extra must be a JSON object")
    return parsed


def _reset_args(options: EpisodeOptions, episode_id: str) -> list[str]:
    args = [
        "reset",
        "--env",
        options.env,
        "--episode-id",
        episode_id,
        "--difficulty",
        options.difficulty,
        "--seed",
        str(options.seed),
        "--max-steps",
        str(options.max_steps),
        "--sandbox",
        options.sandbox,
    ]
    if options.keep_images:
        args.append("--keep-images")
    if options.keep_workspace:
        args.append("--keep-workspace")
    return args


def _new_run_id(options: EpisodeOptions) -> str:
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "-", options.env).strip("-") or "run"
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"


def _fallback_final(failure_mode: str, note: str) -> dict[str, Any]:
    return {
        "verdict": "FAIL",
        "score": 0.0,
        "failure_mode": failure_mode,
        "notes": [note],
    }


def run_episode(options: EpisodeOptions) -> dict[str, Any]:
    """Run one episode and write all requested artifacts.

    The returned mapping contains ``run_id``, ``run_dir``, and the final judge
    object.  API credentials are kept only in this call stack and are never put
    into an environment, subprocess argument, or artifact.
    """

    if options.sandbox not in {"local", "docker"}:
        raise ValueError("sandbox must be local or docker")
    if options.max_steps < 1 or options.max_tokens < 1:
        raise ValueError("max-steps and max-tokens must be positive")
    if options.invalid_retries < 0:
        raise ValueError("invalid-retries must not be negative")
    if not options.model.strip():
        raise ValueError("model must not be empty")
    request_extra = _request_extra(options.request_extra)
    api_key, _ = resolve_credentials(
        options.provider,
        api_key=options.api_key,
        api_key_env=options.api_key_env,
    )
    api_base = resolve_api_base(options.provider, options.api_base)
    run_id = _new_run_id(options)
    artifacts = RunArtifacts(Path(options.out), run_id, secret=api_key)
    episode_id = options.episode_id or f"arena_{run_id.replace('-', '_')}"
    episode_dir: Path | None = None
    final: dict[str, Any] = _fallback_final("not_submitted", "Episode did not reach submission.")
    manifest = manifest_defaults(
        root=ROOT,
        run_id=run_id,
        provider=options.provider,
        api_base=api_base,
        requested_model=options.model,
        environment=options.env,
        difficulty=options.difficulty,
        seed=options.seed,
        sandbox=options.sandbox,
        max_steps=options.max_steps,
        max_tokens=options.max_tokens,
        temperature=options.temperature,
        request_extra=request_extra,
        system_prompt=SYSTEM_PROMPT,
    )
    artifacts.write_manifest(manifest)

    def log_provider_error(record: dict[str, Any]) -> None:
        artifacts.api_error(record)

    client = ProviderClient(
        options.provider,
        api_key,
        api_base=api_base,
        error_logger=log_provider_error,
    )
    history: list[dict[str, str]] = []
    observation = ""
    done = False
    submitted = False
    turn = 0
    resolved_model_seen: str | None = None
    try:
        reset = _run_env_runner(_reset_args(options, episode_id))
        episode_dir = Path(reset.get("info", {}).get("episode_dir", ""))
        if not episode_dir.is_dir():
            # Older/local runners expose the path in state but not in info.
            episode_dir = ROOT / ".episodes" / episode_id
        reset_info = reset.get("info") if isinstance(reset.get("info"), dict) else {}
        agent_info = reset_info.get("agent_image") if isinstance(reset_info.get("agent_image"), dict) else {}
        judge_info = reset_info.get("judge_image") if isinstance(reset_info.get("judge_image"), dict) else {}
        artifacts.update_manifest(
            {
                "episode_id": episode_id,
                "agent_image_id": reset_info.get("agent_image_id") or agent_info.get("id"),
                "judge_image_id": reset_info.get("judge_image_id") or judge_info.get("id"),
                "agent_image_digest": agent_info.get("digest"),
                "judge_image_digest": judge_info.get("digest"),
            }
        )
        artifacts.trace(
            {
                "turn": 0,
                "event": "reset",
                "request_started_at": utc_now(),
                "environment_observation": reset.get("observation"),
                "environment_info": reset_info,
                "reward": reset.get("reward", 0.0),
                "done": reset.get("done", False),
            }
        )
        observation = str(reset.get("observation", ""))
        done = bool(reset.get("done", False))

        while turn < options.max_steps and not done:
            turn += 1
            turn_request_started = utc_now()
            parse_error: str | None = None
            action: dict[str, Any] | None = None
            last_completion: Completion | None = None
            model_output = ""
            invalid_attempts = 0
            for parse_attempt in range(options.invalid_retries + 1):
                request_started = utc_now()
                messages = format_messages(history, observation, parse_error)
                try:
                    completion = client.complete(
                        model=options.model,
                        messages=messages,
                        max_tokens=options.max_tokens,
                        temperature=options.temperature,
                        request_extra=request_extra,
                    )
                except ProviderError as exc:
                    artifacts.api_error(
                        {
                            "attempted_at": utc_now(),
                            "status_code": exc.status_code,
                            "error_type": "provider_error",
                            "body": exc.body,
                            "request_id": exc.request_id,
                            "retryable": exc.retryable,
                            "attempt": exc.attempts,
                        }
                    )
                    parse_error = "provider request failed"
                    artifacts.trace(
                        {
                            "turn": turn,
                            "request_started_at": request_started,
                            "latency_ms": None,
                            "requested_model": options.model,
                            "resolved_model": None,
                            "finish_reason": None,
                            "usage": {},
                            "provider_metadata": {},
                            "raw_model_output": "",
                            "parsed_action": None,
                            "parse_error": parse_error,
                            "retry_count": client.last_retry_count,
                            "environment_observation": observation,
                            "environment_info": {},
                            "reward": 0.0,
                            "done": True,
                        }
                    )
                    done = True
                    final = _fallback_final("api_error", exc.body or str(exc))
                    break
                last_completion = completion
                if completion.resolved_model is not None:
                    resolved_model_seen = completion.resolved_model
                model_output = completion.content
                artifacts.model_response(
                    {
                        "turn": turn,
                        "parse_attempt": parse_attempt,
                        "request_started_at": request_started,
                        "requested_model": completion.requested_model,
                        "resolved_model": completion.resolved_model,
                        "finish_reason": completion.finish_reason,
                        "usage": completion.usage,
                        "latency_ms": completion.latency_ms,
                        "request_id": completion.request_id,
                        "response_headers": completion.response_headers,
                        "raw_response": completion.raw_response,
                        "raw_model_output": completion.content,
                        "retry_count": client.last_retry_count,
                    }
                )
                action, parse_error = parse_action(model_output)
                if action is not None:
                    break
                invalid_attempts += 1
            if done and last_completion is None:
                break

            if action is None:
                env_response = {
                    "observation": f"Model failed to produce a valid JSON action: {parse_error}",
                    "reward": 0.0,
                    "done": True,
                    "info": {"failure": "invalid_action"},
                }
                final = _fallback_final("invalid_action", parse_error or "invalid action")
                done = True
                completion = last_completion
                artifacts.trace(
                    {
                        "turn": turn,
                        "request_started_at": turn_request_started,
                        "latency_ms": completion.latency_ms if completion else None,
                        "requested_model": options.model,
                        "resolved_model": completion.resolved_model if completion else None,
                        "finish_reason": completion.finish_reason if completion else None,
                        "usage": completion.usage if completion else {},
                        "provider_metadata": provider_metadata(completion) if completion else {},
                        "raw_model_output": model_output,
                        "parsed_action": None,
                        "parse_error": parse_error,
                        "retry_count": client.last_retry_count,
                        "invalid_action_attempts": invalid_attempts,
                        "environment_observation": env_response["observation"],
                        "environment_info": env_response["info"],
                        "reward": 0.0,
                        "done": True,
                    }
                )
                break

            env_response = _run_env_runner(
                [
                    "step",
                    "--episode",
                    episode_id,
                    "--action",
                    json.dumps(action, ensure_ascii=False),
                ]
            )
            completion = last_completion
            env_info = env_response.get("info") if isinstance(env_response.get("info"), dict) else {}
            artifacts.trace(
                {
                    "turn": turn,
                    "request_started_at": turn_request_started,
                    "latency_ms": completion.latency_ms if completion else None,
                    "requested_model": options.model,
                    "resolved_model": completion.resolved_model if completion else None,
                    "finish_reason": completion.finish_reason if completion else None,
                    "usage": completion.usage if completion else {},
                    "provider_metadata": provider_metadata(completion) if completion else {},
                    "raw_model_output": model_output,
                    "parsed_action": action,
                    "parse_error": None,
                    "retry_count": client.last_retry_count,
                    "invalid_action_attempts": invalid_attempts,
                    "environment_observation": env_response.get("observation", ""),
                    "environment_info": env_info,
                    "reward": env_response.get("reward", 0.0),
                    "done": env_response.get("done", False),
                }
            )
            observation = str(env_response.get("observation", ""))
            done = bool(env_response.get("done", False))
            requested_submit = action.get("type") == "submit"
            if requested_submit:
                candidate = env_info.get("judge_result")
                if isinstance(candidate, dict):
                    final = candidate
                submitted = bool(env_response.get("done")) and not env_info.get("submit_blocked", False)
            history.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            history.append({"role": "user", "content": clip(observation)})
            if submitted:
                break

        # A model normally submits explicitly.  The controller submits once at
        # the end as well, so max-step exhaustion still yields a judge result.
        if not submitted and final.get("failure_mode") not in {"api_error", "invalid_action"}:
            submit_response = _run_env_runner(
                ["submit", "--episode", episode_id, "--confirm"]
            )
            submit_info = submit_response.get("info") if isinstance(submit_response.get("info"), dict) else {}
            candidate = submit_info.get("judge_result")
            if isinstance(candidate, dict):
                final = candidate
            else:
                parsed = _extract_json_object(str(submit_response.get("observation", "")))
                if parsed is not None:
                    final = parsed
            artifacts.trace(
                {
                    "turn": turn + 1,
                    "event": "automatic_submit",
                    "request_started_at": utc_now(),
                    "latency_ms": None,
                    "requested_model": options.model,
                    "resolved_model": None,
                    "finish_reason": None,
                    "usage": {},
                    "provider_metadata": {},
                    "raw_model_output": "",
                    "parsed_action": {"type": "submit", "confirm": True},
                    "parse_error": None,
                    "retry_count": 0,
                    "environment_observation": submit_response.get("observation", ""),
                    "environment_info": submit_info,
                    "reward": submit_response.get("reward", 0.0),
                    "done": submit_response.get("done", True),
                }
            )
    except Exception as exc:
        final = _fallback_final("controller_error", str(exc))
        artifacts.trace(
            {
                "turn": turn,
                "event": "controller_error",
                "error": str(exc),
                "done": True,
            }
        )
    finally:
        if episode_dir is None:
            episode_dir = ROOT / ".episodes" / episode_id
        manifest_updates: dict[str, Any] = {
            "resolved_model": final.get("resolved_model") or resolved_model_seen
        }
        # The generated state is the authoritative source for image IDs when the
        # reset response came from an older env_runner.
        state_path = episode_dir / "state.json"
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                agent_info = state.get("agent_image") if isinstance(state.get("agent_image"), dict) else {}
                judge_info = state.get("judge_image") if isinstance(state.get("judge_image"), dict) else {}
                manifest_updates.update(
                    {
                        "agent_image_id": state.get("agent_image_id") or agent_info.get("id"),
                        "judge_image_id": state.get("judge_image_id") or judge_info.get("id"),
                        "agent_image_digest": state.get("agent_image_digest") or agent_info.get("digest"),
                        "judge_image_digest": state.get("judge_image_digest") or judge_info.get("digest"),
                    }
                )
            except (OSError, json.JSONDecodeError):
                pass
        artifacts.finalize(episode_dir=episode_dir, final=final, finished_at=utc_now())
        artifacts.update_manifest(manifest_updates)
        if options.sandbox == "docker" and not options.keep_images and state_path.is_file():
            try:
                cleanup_state = json.loads(state_path.read_text(encoding="utf-8"))
                if not cleanup_state.get("images_removed"):
                    DockerBackend().remove_images(
                        (cleanup_state.get("agent_image") or {}).get("name"),
                        (cleanup_state.get("judge_image") or {}).get("name"),
                    )
            except (OSError, json.JSONDecodeError, RuntimeError):
                pass
        if not options.keep_workspace and episode_dir.exists():
            shutil.rmtree(episode_dir, ignore_errors=True)

    return {"run_id": run_id, "run_dir": str(artifacts.root), "final": final}


__all__ = [
    "EpisodeOptions",
    "MAX_HISTORY_CHARS",
    "MAX_OBS_CHARS",
    "ROOT",
    "SYSTEM_PROMPT",
    "_extract_json_object",
    "_request_extra",
    "clip",
    "format_messages",
    "parse_action",
    "run_episode",
]
