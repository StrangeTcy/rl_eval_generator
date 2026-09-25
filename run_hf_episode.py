#!/usr/bin/env python3
"""Backward-compatible wrapper around :mod:`arena`.

The historical filename and flags are retained for users with existing scripts,
but requests now use the provider-neutral OpenAI-compatible client.  In
particular, there is no implicit legacy Hugging Face text-generation fallback:
a failed chat request is reported once (apart from bounded transient retries).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from arena.episode import EpisodeOptions, format_messages, parse_action, run_episode
from arena.providers import ProviderClient, open_no_redirect, require_https

ROOT = Path(__file__).resolve().parent
DEFAULT_API_BASE = "https://router.huggingface.co/v1"
MAX_OBS_CHARS = 12000
MAX_HISTORY_CHARS = 28000
SYSTEM_PROMPT = (
    "You are an autonomous coding agent. Return exactly one JSON action object "
    "for the current environment observation."
)

__all__ = [
    "DEFAULT_API_BASE",
    "MAX_HISTORY_CHARS",
    "MAX_OBS_CHARS",
    "SYSTEM_PROMPT",
    "call_hf_chat",
    "clip",
    "format_messages",
    "hf_headers",
    "main",
    "parse_action",
    "post_json",
    "run_env_runner",
]


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]..."


def run_env_runner(args: list[str]) -> dict[str, Any]:
    """Compatibility wrapper for callers that used the old helper."""

    import subprocess

    env = os.environ.copy()
    for name in list(env):
        upper = name.upper()
        if upper in {"OPENROUTER_API_KEY", "HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN", "API_KEY"} or "API_KEY" in upper or upper.endswith("_TOKEN"):
            env.pop(name, None)
    proc = subprocess.run(
        [sys.executable, "env_runner.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    return json.loads(proc.stdout)


def hf_headers(token: str | None) -> dict[str, str]:
    """Compatibility helper; callers should prefer ProviderClient."""

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def post_json(
    url: str,
    payload: dict[str, Any],
    token: str | None,
    timeout: int = 120,
) -> dict[str, Any] | list[Any]:
    """Compatibility helper using the same single chat endpoint as the arena."""

    import json as _json
    from urllib import request

    require_https(url)
    data = _json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers=hf_headers(token), method="POST")
    with open_no_redirect(req, timeout=timeout) as response:
        loaded = _json.loads(response.read().decode("utf-8"))
    return loaded


def call_hf_chat(
    model: str,
    messages: list[dict[str, str]],
    token: str | None,
    api_base: str = DEFAULT_API_BASE,
    max_new_tokens: int = 1024,
    temperature: float = 0.0,
) -> str:
    """Call modern Hugging Face chat completions without a legacy fallback."""

    if not token:
        raise ValueError("HF token is required")
    client = ProviderClient("huggingface", token, api_base=api_base)
    completion = client.complete(
        model=model,
        messages=messages,
        max_tokens=max_new_tokens,
        temperature=temperature,
    )
    return completion.content


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an env_runner episode with a Hugging Face OpenAI-compatible model."
    )
    parser.add_argument("--model", required=True, help="Hugging Face model id")
    parser.add_argument("--env", default="rope")
    parser.add_argument("--difficulty", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--out", default="", help="Legacy JSONL trace path")
    parser.add_argument("--hf-token", default="", help="HF token; defaults to HF_TOKEN")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument(
        "--provider",
        choices=("huggingface", "openrouter", "custom"),
        default="",
        help="Compatibility override; otherwise inferred from --api-base.",
    )
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--invalid-retries", type=int, default=2)
    parser.add_argument("--sandbox", choices=("local", "docker"), default="local")
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()

    provider = args.provider or (
        "openrouter" if "openrouter.ai" in args.api_base else "huggingface"
    )
    token = args.hf_token or (
        os.environ.get("OPENROUTER_API_KEY") if provider == "openrouter" else None
    ) or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    episode_id = args.episode_id or f"hf_{args.env}"
    out_path = Path(args.out or f"runs/{episode_id}.jsonl")
    result = run_episode(
        EpisodeOptions(
            provider=provider,
            model=args.model,
            api_key=token,
            env=args.env,
            difficulty=args.difficulty,
            seed=args.seed,
            max_steps=args.max_steps,
            max_tokens=args.max_new_tokens,
            temperature=args.temperature,
            api_base=args.api_base,
            sandbox=args.sandbox,
            out=out_path.parent,
            invalid_retries=args.invalid_retries,
            episode_id=episode_id,
            keep_images=args.keep_images,
            keep_workspace=args.keep_workspace,
        )
    )
    trace_source = Path(result["run_dir"]) / "trace.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(trace_source, out_path)
    print(json.dumps({**result, "trace": str(out_path)}, indent=2, ensure_ascii=False))
    return 0 if result.get("final", {}).get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
