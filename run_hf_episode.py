#!/usr/bin/env python3
"""Run one generated environment episode using a Hugging Face chat/completion model.

The model controls the environment by emitting one JSON action per turn. The
runner executes the action through env_runner.py, records the trace, and repeats
until done or max steps.

Token handling:
  - read from --hf-token, HF_TOKEN, or HUGGINGFACEHUB_API_TOKEN
  - never printed
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

ROOT = Path(__file__).resolve().parent
DEFAULT_API_BASE = "https://api-inference.huggingface.co/models"
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
- {"type": "submit"}

Do not use Markdown. Do not explain. Return only the action JSON.
For code edits, prefer a small unified diff via apply_patch. Use apply_patch_base64 only for a base64-encoded unified diff; never encode JSON edit instructions as patch_base64.
The current working directory for shell commands is the environment workspace.
"""


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def run_env_runner(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, "env_runner.py", *args], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    return json.loads(proc.stdout)


def parse_action(text: str) -> tuple[dict[str, Any] | None, str | None]:
    raw = text.strip()
    # Drop common chat wrappers.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    candidates = [raw]
    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        action = None
        try:
            action = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(candidate)
                if isinstance(parsed, dict):
                    action = parsed
            except Exception:
                action = None
        if isinstance(action, dict):
            if "action" in action and isinstance(action["action"], dict):
                action = action["action"]
            if "type" in action or "cmd" in action:
                return action, None
            return None, "JSON object must contain either 'type' or 'cmd'"
    if '"type"' in raw and '"write_file"' in raw:
        return None, "Could not parse write_file JSON. Escape newlines/quotes or use apply_patch_base64."
    if '"type"' in raw and '"apply_patch"' in raw:
        return None, "Could not parse patch JSON. Use apply_patch_base64 for multiline diffs."
    return None, "Could not parse a valid JSON action"


def hf_headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def post_json(url: str, payload: dict[str, Any], token: str | None, timeout: int = 120) -> dict[str, Any] | list[Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=hf_headers(token), method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HF HTTP {exc.code}: {body}") from exc


def format_messages(history: list[dict[str, str]], observation: str, invalid_note: str | None = None) -> list[dict[str, str]]:
    user = "Current observation:\n" + clip(observation, MAX_OBS_CHARS)
    if invalid_note:
        user += "\n\nYour previous response was invalid: " + invalid_note + "\nReturn exactly one valid JSON action. If you need to edit multiple lines, return a small unified diff in apply_patch, or base64-encode a unified diff in apply_patch_base64. Do not encode JSON edit specs as patch_base64."
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user})

    # Keep tail if history becomes too large.
    while sum(len(m["content"]) for m in messages) > MAX_HISTORY_CHARS and len(messages) > 3:
        del messages[1]
    return messages


def call_hf_chat(model: str, messages: list[dict[str, str]], token: str | None, api_base: str, max_new_tokens: int, temperature: float) -> str:
    # Prefer OpenAI-compatible chat completion exposed by modern HF inference providers.
    base = api_base.rstrip('/')
    if base.endswith('/v1'):
        url = f"{base}/chat/completions"
    elif 'router.huggingface.co' in base:
        url = f"{base}/v1/chat/completions"
    else:
        url = f"{base}/{model}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_new_tokens,
        "temperature": temperature,
    }
    try:
        data = post_json(url, payload, token)
        return data["choices"][0]["message"]["content"]
    except Exception:
        # Fallback to classic HF text-generation endpoint.
        prompt = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages) + "\nASSISTANT:"
        url = f"{api_base.rstrip('/')}/{model}"
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
                "return_full_text": False,
            },
            "options": {"wait_for_model": True},
        }
        data = post_json(url, payload, token)
        if isinstance(data, list) and data and "generated_text" in data[0]:
            return data[0]["generated_text"]
        if isinstance(data, dict) and "generated_text" in data:
            return data["generated_text"]
        raise RuntimeError(f"Unexpected HF response: {data!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an env_runner episode with a Hugging Face model.")
    parser.add_argument("--model", required=True, help="HF model id")
    parser.add_argument("--env", default="rope")
    parser.add_argument("--difficulty", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--out", default="", help="Trace JSONL path")
    parser.add_argument("--hf-token", default="", help="HF token; defaults to HF_TOKEN env var")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--invalid-retries", type=int, default=2)
    args = parser.parse_args()

    token = args.hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    episode_id = args.episode_id or f"hf_{args.env}_{int(time.time())}"
    out_path = Path(args.out or f"runs/{episode_id}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    reset = run_env_runner([
        "reset",
        "--env", args.env,
        "--episode-id", episode_id,
        "--difficulty", args.difficulty,
        "--seed", str(args.seed),
        "--max-steps", str(args.max_steps),
    ])
    history: list[dict[str, str]] = []
    observation = reset["observation"]
    done = reset["done"]
    final_reward = reset["reward"]

    with out_path.open("w", encoding="utf-8") as trace:
        trace.write(json.dumps({"turn": 0, "event": "reset", "env_response": reset}, ensure_ascii=False) + "\n")

        for turn in range(1, args.max_steps + 1):
            if done:
                break
            invalid_note = None
            model_output = ""
            action = None
            for attempt in range(args.invalid_retries + 1):
                messages = format_messages(history, observation, invalid_note)
                model_output = call_hf_chat(args.model, messages, token, args.api_base, args.max_new_tokens, args.temperature)
                action, invalid_note = parse_action(model_output)
                if action is not None:
                    break
            if action is None:
                env_response = {
                    "observation": f"Model failed to produce a valid JSON action: {invalid_note}",
                    "reward": 0.0,
                    "done": True,
                    "info": {"failure": "invalid_action"},
                }
                trace.write(json.dumps({"turn": turn, "model_output": model_output, "action": None, "env_response": env_response}, ensure_ascii=False) + "\n")
                done = True
                final_reward = 0.0
                break

            env_response = run_env_runner(["step", "--episode", episode_id, "--action", json.dumps(action)])
            observation = env_response["observation"]
            done = env_response["done"]
            final_reward = env_response["reward"]
            history.append({"role": "assistant", "content": json.dumps(action)})
            history.append({"role": "user", "content": clip(observation, MAX_OBS_CHARS)})
            trace.write(json.dumps({"turn": turn, "model_output": model_output, "action": action, "env_response": env_response}, ensure_ascii=False) + "\n")

        progress_response = None
        try:
            progress_response = run_env_runner(["step", "--episode", episode_id, "--action", json.dumps({"type": "progress"})])
        except Exception:
            progress_response = None
        summary = {
            "event": "summary",
            "episode_id": episode_id,
            "model": args.model,
            "env": args.env,
            "difficulty": args.difficulty,
            "seed": args.seed,
            "done": done,
            "final_reward": final_reward,
            "progress_score": (progress_response or {}).get("info", {}).get("progress_score"),
            "progress": (progress_response or {}).get("info"),
            "trace": str(out_path),
        }
        trace.write(json.dumps(summary, ensure_ascii=False) + "\n")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
