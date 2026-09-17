#!/usr/bin/env python3
"""Command-line entry point for the provider-neutral evaluation arena."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from arena.artifacts import summarize_run
from arena.episode import EpisodeOptions, run_episode
from arena.providers import (
    PROVIDERS,
    ProviderClient,
    ProviderError,
    resolve_api_base,
    resolve_credentials,
)
from arena.trajectory_runner import (
    TrajectoryOptions,
    parse_int_values,
    parse_seed_range,
    parse_values,
    run_trajectory,
)
from arena.trajectory_runner import (
    write_summary as write_trajectory_summary,
)

REVIEW_PROMPT = """Review this recurrent-depth evaluation result in no more than 300 words.

Distinguish:
1. observations directly supported by the trace;
2. likely agent-strategy explanations;
3. claims that cannot be inferred about the model's internal architecture.

Comment on benchmark confounds, depth scaling, token efficiency,
tool-use quality, and the next experiment that would be most informative.
Do not use marketing language.

Run artifacts:
"""


def _request_extra_arg(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return parsed


def _common_provider_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (environment variables are safer than shell arguments).",
    )
    parser.add_argument("--api-key-env", default=None, help="Environment variable containing the API key.")
    parser.add_argument("--api-base", default=None, help="OpenAI-compatible API base URL.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run provider-neutral, Docker-backed generated-environment evaluations."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="generate an environment and run an API-controlled episode")
    _common_provider_args(run)
    run.add_argument("--env", required=True)
    run.add_argument("--difficulty", required=True, help="comma-separated difficulty levels")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--max-steps", type=int, default=30)
    run.add_argument("--max-tokens", type=int, default=1024)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--request-extra", type=_request_extra_arg, default={})
    run.add_argument("--sandbox", choices=("docker", "local"), default="docker")
    run.add_argument("--out", type=Path, default=Path("runs"), help="directory containing run directories")
    run.add_argument("--invalid-retries", type=int, default=2)
    run.add_argument("--keep-images", action="store_true")
    run.add_argument("--keep-workspace", action="store_true")

    trajectory = sub.add_parser(
        "trajectory",
        help="run the direct-answer trajectory-semantics behavioral benchmark",
    )
    _common_provider_args(trajectory)
    trajectory.add_argument("--out", type=Path, required=True)
    trajectory.add_argument("--representations", default="flat,reflective")
    trajectory.add_argument("--witnesses", default="valid,broken")
    trajectory.add_argument(
        "--queries",
        default="parse_only,one_step,state_at_T,template_at_T,complete_return",
    )
    trajectory.add_argument("--horizons", default="1,6,30,126,510")
    trajectory.add_argument("--relabelings", default="canonical,permuted_templates,recoded_payloads")
    trajectory.add_argument("--syntax-noise", default="clean,noisy")
    trajectory.add_argument(
        "--semantic-seeds",
        default=None,
        help="inclusive comma-separated seeds or ranges (default: 0:4)",
    )
    trajectory.add_argument("--seed", type=int, default=None, help="single semantic seed convenience alias")
    trajectory.add_argument(
        "--presentation-seeds",
        default=None,
        help="one independent presentation seed per semantic seed (default: derived, disjoint seeds)",
    )
    trajectory.add_argument(
        "--resource-protocol",
        choices=("answer_only", "external_scratchpad"),
        default="answer_only",
    )
    trajectory.add_argument("--api-replications", type=int, default=1)
    trajectory.add_argument("--max-tokens", type=int, default=64)
    trajectory.add_argument("--temperature", type=float, default=0.0)
    trajectory.add_argument("--limit", type=int, default=None)

    trajectory_analysis = sub.add_parser(
        "trajectory-analyze",
        aliases=("trajectory-summary", "trajectory-analysis"),
        help="rebuild summary artifacts for a direct-answer trajectory run",
    )
    trajectory_analysis.add_argument("run_dir", type=Path)

    summary = sub.add_parser("summarize", help="write summary.csv and summary.md for a run")
    summary.add_argument("run_dir", type=Path)

    review = sub.add_parser("review", help="ask a provider to review an existing run")
    _common_provider_args(review)
    review.add_argument("--run-dir", type=Path, required=True)
    review.add_argument("--max-tokens", type=int, default=700)
    review.add_argument("--temperature", type=float, default=0.2)

    return parser


def _run(args: argparse.Namespace) -> int:
    options = EpisodeOptions(
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        api_key_env=args.api_key_env,
        api_base=args.api_base,
        env=args.env,
        difficulty=args.difficulty,
        seed=args.seed,
        max_steps=args.max_steps,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        request_extra=args.request_extra,
        sandbox=args.sandbox,
        out=args.out,
        invalid_retries=args.invalid_retries,
        keep_images=args.keep_images,
        keep_workspace=args.keep_workspace,
    )
    result = run_episode(options)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("final", {}).get("verdict") == "PASS" else 1


def _trajectory(args: argparse.Namespace) -> int:
    options = TrajectoryOptions(
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        api_key_env=args.api_key_env,
        api_base=args.api_base,
        out=args.out,
        representations=parse_values(args.representations),
        witnesses=parse_values(args.witnesses),
        queries=parse_values(args.queries),
        horizons=parse_int_values(args.horizons),
        relabelings=parse_values(args.relabelings),
        syntax_noise=parse_values(args.syntax_noise),
        semantic_seeds=parse_seed_range(
            args.semantic_seeds
            if args.semantic_seeds is not None
            else str(args.seed) if args.seed is not None else "0:4"
        ),
        presentation_seeds=(
            parse_seed_range(args.presentation_seeds)
            if args.presentation_seeds is not None
            else None
        ),
        resource_protocol=args.resource_protocol,
        api_replications=args.api_replications,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        limit=args.limit,
    )
    result = run_trajectory(options)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _trajectory_analyze(args: argparse.Namespace) -> int:
    manifest = args.run_dir / "manifest.json"
    records: list[dict[str, Any]] = []
    trace = args.run_dir / "trace.jsonl"
    if not trace.is_file():
        raise ValueError(f"trajectory trace not found: {trace}")
    for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if value.get("event") == "case_result":
            records.append(value)
    manifest_value = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
    summary_value = write_trajectory_summary(args.run_dir, records, manifest_value)
    print(json.dumps({"summary": str(args.run_dir / "summary.json"), **summary_value}, indent=2))
    return 0


def _summarize(args: argparse.Namespace) -> int:
    csv_path, md_path = summarize_run(args.run_dir)
    print(json.dumps({"summary_csv": str(csv_path), "summary_md": str(md_path)}, indent=2))
    return 0


def _review(args: argparse.Namespace) -> int:
    api_key, _ = resolve_credentials(
        args.provider, api_key=args.api_key, api_key_env=args.api_key_env
    )
    api_base = resolve_api_base(args.provider, args.api_base)
    run_dir = args.run_dir
    pieces: list[str] = []
    for name, limit in (
        ("manifest.json", 12000),
        ("final.json", 16000),
        ("summary.md", 12000),
        ("trace.jsonl", 50000),
    ):
        path = run_dir / name
        if path.is_file():
            pieces.append(f"\n--- {name} ---\n{path.read_text(encoding='utf-8', errors='replace')[:limit]}")
    client = ProviderClient(args.provider, api_key, api_base=api_base)
    completion = client.complete(
        model=args.model,
        messages=[{"role": "user", "content": REVIEW_PROMPT + "".join(pieces)}],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    review_path = run_dir / "review.md"
    review_path.write_text(completion.content.rstrip() + "\n", encoding="utf-8")
    result = {
        "model": args.model,
        "resolved_model": completion.resolved_model,
        "request_id": completion.request_id,
        "usage": completion.usage,
        "latency_ms": completion.latency_ms,
        "review": completion.content,
    }
    (run_dir / "review.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"review": str(review_path), "review_json": str(run_dir / 'review.json')}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "trajectory":
            return _trajectory(args)
        if args.command in {"trajectory-analyze", "trajectory-summary", "trajectory-analysis"}:
            return _trajectory_analyze(args)
        if args.command == "summarize":
            return _summarize(args)
        return _review(args)
    except (ValueError, ProviderError, OSError, RuntimeError) as exc:
        # ProviderError bodies are sanitized by providers.py.  Do not include
        # argparse Namespace or request payloads in this message.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
