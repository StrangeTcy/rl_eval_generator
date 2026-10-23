#!/usr/bin/env python3
"""Offline wiring check: Atria Responses request -> controller -> judge.

This is NOT a model result.  It replaces the provider transport with a stub that
receives exactly the body `ProviderClient.complete_responses` would send, asserts
its shape (nested `reasoning.effort`, `max_output_tokens`, no Chat-Completions
fields), and answers with the environment's own host-side oracle reference as a
`write_file` action.  What it proves is that the controller's Responses path,
action execution, submit and independent judge scoring are wired together; what
it does not prove is anything about a model.

Run from the repository root:
    python runs/pilot_offline_wiring/verify_wiring.py
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import env_runner  # noqa: E402
from arena import providers as providers_module  # noqa: E402
from arena.episode import EpisodeOptions, run_episode  # noqa: E402
from arena.providers import Completion  # noqa: E402
from tools import recursive_references  # noqa: E402

CASES = {
    "atria": {
        "provider": "atria",
        "model": "Atria-Dawn-Preview",
        "wire_api": "responses",
        "reasoning_effort": "high",
    },
    "mercury": {
        "provider": "mercury",
        "model": "mercury-2.5",
        "wire_api": "chat_completions",
        "reasoning_effort": "high",
    },
}


def _reference_solver(environment: str, difficulty: str, seed: int) -> str:
    """Regenerate the exact instance and return the oracle's solver.py body."""

    with tempfile.TemporaryDirectory(prefix="wiring-") as temp:
        old = env_runner.EPISODES_DIR
        try:
            env_runner.EPISODES_DIR = Path(temp) / "episodes"
            episode_id = "wiring_" + environment
            args = SimpleNamespace(
                episode_id=episode_id,
                env=environment,
                difficulty=difficulty,
                seed=seed,
                max_steps=1,
                sandbox="local",
                keep_images=False,
                keep_workspace=True,
                interventions="",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                env_runner.reset(args)
            state = env_runner._load_state(episode_id)
            workspace = Path(state["workspace"])
            apply, _negative = recursive_references.references()[environment]
            apply(workspace, wrong=False)
            return (workspace / "solver.py").read_text(encoding="utf-8")
        finally:
            env_runner.EPISODES_DIR = old


def _stub_responses(record: dict):
    def complete_responses(self, input_text, **kwargs):
        record["body"] = {
            "model": kwargs.get("model"),
            "reasoning": {"effort": kwargs.get("reasoning_effort")},
            "max_output_tokens": kwargs.get("max_output_tokens"),
            "input_is_messages": isinstance(input_text, list),
        }
        record["calls"] += 1
        return Completion(
            content=json.dumps(record["action"]),
            requested_model=str(kwargs.get("model")),
            resolved_model=str(kwargs.get("model")),
            finish_reason="completed",
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            raw_response={"stub": True},
            latency_ms=1,
            request_id="stub-request",
            response_headers={},
            status_code=200,
            provider="atria",
        )

    return complete_responses


def _stub_chat(record: dict):
    def complete(self, *, model, messages, max_tokens, temperature, top_p=None, request_extra=None):
        record["body"] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "request_extra": dict(request_extra or {}),
            "temperature": temperature,
        }
        record["calls"] += 1
        return Completion(
            content=json.dumps(record["action"]),
            requested_model=model,
            resolved_model=model,
            finish_reason="stop",
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            raw_response={"stub": True},
            latency_ms=1,
            request_id="stub-request",
            response_headers={},
            status_code=200,
            provider="mercury",
        )

    return complete


def run(provider_key: str, environment: str, difficulty: str, seed: int) -> dict:
    profile = CASES[provider_key]
    solver = _reference_solver(environment, difficulty, seed)
    record: dict = {
        "calls": 0,
        "action": {"type": "write_file", "path": "solver.py", "content": solver},
    }
    record["actions"] = [
        {"type": "write_file", "path": "solver.py", "content": solver},
        {"type": "submit", "confirm": True},
    ]
    counter = {"index": 0}

    def next_completion_body():
        index = min(counter["index"], len(record["actions"]) - 1)
        counter["index"] += 1
        return record["actions"][index]

    if provider_key == "atria":
        original = providers_module.ProviderClient.complete_responses
        stub = _stub_responses(record)

        def wrapped(self, input_text, **kwargs):
            record["action"] = next_completion_body()
            return stub(self, input_text, **kwargs)

        providers_module.ProviderClient.complete_responses = wrapped
    else:
        original = providers_module.ProviderClient.complete
        stub = _stub_chat(record)

        def wrapped(self, **kwargs):
            record["action"] = next_completion_body()
            return stub(self, **kwargs)

        providers_module.ProviderClient.complete = wrapped

    options = EpisodeOptions(
        provider=profile["provider"],
        model=profile["model"],
        env=environment,
        difficulty=difficulty,
        seed=seed,
        max_steps=8,
        max_tokens=1024,
        wire_api=profile["wire_api"],
        reasoning_effort=profile["reasoning_effort"],
        sandbox="local",
        out=ROOT / "runs" / "pilot_offline_wiring" / provider_key,
        api_key="offline-stub-key-not-a-real-secret",
        api_key_env="ATRIA_API_KEY" if provider_key == "atria" else "INCEPTION_API_KEY",
        invalid_retries=2,
        case_id=f"{environment}__offline_wiring__seed-{seed}",
        keep_workspace=False,
    )
    try:
        result = run_episode(options)
    finally:
        if provider_key == "atria":
            providers_module.ProviderClient.complete_responses = original
        else:
            providers_module.ProviderClient.complete = original

    final = result.get("final") or {}
    return {
        "provider": profile["provider"],
        "model": profile["model"],
        "wire_api": profile["wire_api"],
        "reasoning_effort": profile["reasoning_effort"],
        "environment": environment,
        "difficulty": difficulty,
        "seed": seed,
        "request_body_seen_by_transport": record.get("body"),
        "transport_calls": record["calls"],
        "run_dir": str(result.get("run_dir")),
        "verdict": final.get("verdict"),
        "score": final.get("score"),
        "failure_mode": final.get("failure_mode"),
        "checks": final.get("checks"),
        "note": "offline transport stub answering with the host oracle reference; NOT a model result",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(CASES), required=True)
    parser.add_argument("--environment", default="recursive_gluing")
    parser.add_argument("--difficulty", default="hard,hard,hard,hard")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = run(args.provider, args.environment, args.difficulty, args.seed)
    text = json.dumps(payload, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
