"""Host-side direct-answer runner for trajectory-semantics cases."""
from __future__ import annotations

import csv
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import append_jsonl, sha256_text, utc_now, write_json
from .providers import (
    ProviderClient,
    ProviderError,
    provider_metadata,
    resolve_api_base,
    resolve_credentials,
)
from .trajectory import certification, make_case, make_messages, public_case, score_answer


@dataclass
class TrajectoryOptions:
    provider: str
    model: str
    out: Path
    representations: list[str]
    witnesses: list[str]
    queries: list[str]
    horizons: list[int]
    relabelings: list[str]
    syntax_noise: list[str]
    semantic_seeds: list[int]
    presentation_seeds: list[int] | None = None
    resource_protocol: str = "answer_only"
    api_replications: int = 1
    max_tokens: int = 64
    temperature: float = 0.0
    api_key: str | None = None
    api_key_env: str | None = None
    api_base: str | None = None
    limit: int | None = None


def parse_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_values(value: str) -> list[int]:
    result: list[int] = []
    for item in parse_values(value):
        result.append(int(item))
    return result


def parse_seed_range(value: str) -> list[int]:
    """Parse ``0:49`` as an inclusive range, plus comma-separated seeds."""

    result: list[int] = []
    for item in parse_values(value):
        if ":" not in item:
            result.append(int(item))
            continue
        start_text, end_text = item.split(":", 1)
        start, end = int(start_text), int(end_text)
        if end < start:
            raise ValueError("semantic seed range must be ascending")
        result.extend(range(start, end + 1))
    return result


def _run_id() -> str:
    return f"trajectory-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"


def _manifest(options: TrajectoryOptions, run_id: str, certification_by_seed: dict[int, dict[str, object]]) -> dict[str, object]:
    api_base = resolve_api_base(options.provider, options.api_base)
    return {
        "run_id": run_id,
        "started_at": utc_now(),
        "finished_at": None,
        "benchmark_family": "trajectory_semantics",
        "scoreboard": "trajectory_direct_answer",
        "system_family": "relay",
        "provider": options.provider,
        "api_base": api_base,
        "requested_model": options.model,
        "resolved_model": None,
        "representations": options.representations,
        "witnesses": options.witnesses,
        "queries": options.queries,
        "horizons": options.horizons,
        "relabelings": options.relabelings,
        "syntax_noise": options.syntax_noise,
        "semantic_seeds": options.semantic_seeds,
        "presentation_seeds": options.presentation_seeds,
        "resource_protocol": options.resource_protocol,
        "api_replications": options.api_replications,
        "max_output_tokens": options.max_tokens,
        "temperature": options.temperature,
        "system_prompt_sha256": sha256_text(make_messages_placeholder(options.resource_protocol)[0]["content"]),
        "certification_by_seed": certification_by_seed,
        "epistemic": {
            "supported": ["behavioral_sensitivity_to_named_interventions"],
            "not_supported": [
                "serial_depth_measurement",
                "internal_algorithm_identification",
                "instance_complexity_lower_bound",
            ],
        },
    }


def make_messages_placeholder(protocol: str) -> list[dict[str, str]]:
    from .trajectory import SYSTEM_ANSWER_ONLY, SYSTEM_SCRATCHPAD

    system = SYSTEM_SCRATCHPAD if protocol == "external_scratchpad" else SYSTEM_ANSWER_ONLY
    return [{"role": "system", "content": system}]


def _group_key(record: dict[str, Any]) -> tuple[object, ...]:
    case = record.get("case") or {}
    return tuple(case.get(key) for key in ("representation", "witness_status_for_query", "query_type", "horizon", "relabeling"))


def write_summary(run_dir: Path, records: list[dict[str, Any]], manifest: dict[str, object]) -> dict[str, Any]:
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(_group_key(record), []).append(record)
    rows: list[dict[str, Any]] = []
    for key, items in sorted(groups.items(), key=lambda pair: str(pair[0])):
        correct = sum(bool(item.get("correct")) for item in items)
        rows.append(
            {
                "representation": key[0],
                "witness_status_for_query": key[1],
                "query_type": key[2],
                "horizon": key[3],
                "relabeling": key[4],
                "n": len(items),
                "correct": correct,
                "accuracy": correct / max(1, len(items)),
                "format_valid_rate": sum(bool(item.get("format_valid")) for item in items) / max(1, len(items)),
                "stale_witness_match_rate": sum(bool(item.get("matched_stale_witness_prediction")) for item in items) / max(1, len(items)),
            }
        )
    csv_path = run_dir / "summary.csv"
    fields = list(rows[0]) if rows else ["representation", "query_type", "accuracy"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "event": "summary",
        "total_cases": len(records),
        "correct": sum(bool(item.get("correct")) for item in records),
        "accuracy": sum(bool(item.get("correct")) for item in records) / max(1, len(records)),
        "group_count": len(rows),
        "groups": rows,
        "interpretation_warning": "These are behavioral intervention results, not a serial-depth measurement.",
    }
    write_json(run_dir / "summary.json", summary)
    markdown = [
        "# Trajectory-semantics summary",
        "",
        f"- Total cases: `{summary['total_cases']}`",
        f"- Accuracy: `{summary['accuracy']}`",
        "- Interpretation: behavioral sensitivity to named interventions; no internal depth claim.",
        "",
        "| representation | witness status | query | horizon | relabeling | n | accuracy | stale-witness match |",
        "|---|---|---|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        markdown.append(
            f"| {row['representation']} | {row['witness_status_for_query']} | {row['query_type']} | "
            f"{row['horizon']} | {row['relabeling']} | {row['n']} | {row['accuracy']:.3f} | "
            f"{row['stale_witness_match_rate']:.3f} |"
        )
    (run_dir / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return summary


def run_trajectory(options: TrajectoryOptions) -> dict[str, Any]:
    if options.api_replications < 1:
        raise ValueError("api-replications must be positive")
    if not options.semantic_seeds:
        raise ValueError("at least one semantic seed is required")
    if len(set(options.semantic_seeds)) != len(options.semantic_seeds):
        raise ValueError("semantic seeds must be distinct")
    presentation_seeds = options.presentation_seeds or [
        seed + 1_000_003 for seed in options.semantic_seeds
    ]
    if len(presentation_seeds) != len(options.semantic_seeds):
        raise ValueError("presentation-seeds must have one entry per semantic seed")
    if len(set(presentation_seeds)) != len(presentation_seeds):
        raise ValueError("presentation seeds must be distinct")
    if set(options.semantic_seeds) & set(presentation_seeds):
        raise ValueError("semantic and presentation seed sets must be disjoint")
    options.presentation_seeds = list(presentation_seeds)
    api_key, _ = resolve_credentials(
        options.provider, api_key=options.api_key, api_key_env=options.api_key_env
    )
    api_base = resolve_api_base(options.provider, options.api_base)
    run_dir = Path(options.out)
    run_dir.mkdir(parents=True, exist_ok=False)
    run_id = _run_id()
    certs: dict[int, dict[str, object]] = {}
    for seed in options.semantic_seeds:
        certs[seed] = certification(seed).as_dict()
    manifest = _manifest(options, run_id, certs)
    manifest["api_base"] = api_base
    write_json(run_dir / "manifest.json", manifest, secret=api_key)
    append_jsonl(run_dir / "trace.jsonl", {"event": "reset", "run_id": run_id, "manifest": manifest}, secret=api_key)
    current_case: str | None = None

    def error_logger(record: dict[str, Any]) -> None:
        append_jsonl(
            run_dir / "api_errors.jsonl",
            {"case_id": current_case, **record},
            secret=api_key,
        )

    client = ProviderClient(
        options.provider,
        api_key,
        api_base=api_base,
        error_logger=error_logger,
    )
    records: list[dict[str, Any]] = []
    written_cases: set[str] = set()
    count = 0
    for semantic_seed, presentation_seed in zip(
        options.semantic_seeds, options.presentation_seeds, strict=True
    ):
        cert = certs[semantic_seed]
        for representation in options.representations:
            for witness in options.witnesses:
                for query in options.queries:
                    for horizon in options.horizons:
                        for relabeling in options.relabelings:
                            for syntax_noise in options.syntax_noise:
                                case = make_case(
                                    semantic_seed=semantic_seed,
                                    presentation_seed=presentation_seed,
                                    representation=representation,
                                    witness_state=witness,
                                    query_type=query,
                                    horizon=horizon,
                                    relabeling=relabeling,
                                    syntax_noise=syntax_noise,
                                    resource_protocol=options.resource_protocol,
                                    certification=cert,
                                )
                                messages = make_messages(case, options.resource_protocol)
                                if case.case_id not in written_cases:
                                    append_jsonl(
                                        run_dir / "cases.jsonl",
                                        case.as_dict(include_answer=True),
                                        secret=api_key,
                                    )
                                    written_cases.add(case.case_id)
                                for replication in range(options.api_replications):
                                    if options.limit is not None and count >= options.limit:
                                        break
                                    count += 1
                                    current_case = case.case_id
                                    request_started_at = utc_now()
                                    raw = ""
                                    error: str | None = None
                                    error_status_code: int | None = None
                                    error_retryable: bool | None = None
                                    error_attempts: int | None = None
                                    completion = None
                                    try:
                                        completion = client.complete(
                                            model=options.model,
                                            messages=messages,
                                            max_tokens=options.max_tokens,
                                            temperature=options.temperature,
                                        )
                                        raw = completion.content
                                        scored = score_answer(case, raw)
                                    except ProviderError as exc:
                                        scored = {
                                            "format_valid": False,
                                            "correct": False,
                                            "parsed_answer": "",
                                            "expected_normalized": "",
                                            "matched_stale_witness_prediction": False,
                                        }
                                        error = exc.body or str(exc)
                                        error_status_code = exc.status_code
                                        error_retryable = exc.retryable
                                        error_attempts = exc.attempts
                                    record = {
                                        "event": "case_result",
                                        "case": case.as_dict(include_answer=True),
                                        "case_public": public_case(case),
                                        "messages": messages,
                                        "raw_model_output": raw,
                                        **scored,
                                        "api_replication": replication,
                                        "request_started_at": request_started_at,
                                        "latency_ms": completion.latency_ms if completion else None,
                                        "requested_model": options.model,
                                        "resolved_model": completion.resolved_model if completion else None,
                                        "provider": completion.provider if completion else options.provider,
                                        "upstream_provider": completion.upstream_provider if completion else None,
                                        "finish_reason": completion.finish_reason if completion else None,
                                        "usage": completion.usage if completion else {},
                                        "provider_metadata": provider_metadata(completion) if completion else {},
                                        "response_headers": completion.response_headers if completion else {},
                                        "request_id": completion.request_id if completion else None,
                                        "retry_count": client.last_retry_count,
                                        "error": error,
                                        "error_status_code": error_status_code,
                                        "error_retryable": error_retryable,
                                        "error_attempts": error_attempts,
                                    }
                                    records.append(record)
                                    append_jsonl(run_dir / "trace.jsonl", record, secret=api_key)
                                    append_jsonl(
                                        run_dir / "model_responses.jsonl",
                                        {
                                            "case_id": case.case_id,
                                            "api_replication": replication,
                                            "raw_model_output": raw,
                                            "raw_response": completion.raw_response if completion else {},
                                            "usage": completion.usage if completion else {},
                                            "latency_ms": completion.latency_ms if completion else None,
                                            "request_id": completion.request_id if completion else None,
                                        },
                                        secret=api_key,
                                    )
                                    append_jsonl(
                                        run_dir / "answers.jsonl",
                                        {
                                            "case_id": case.case_id,
                                            "api_replication": replication,
                                            "raw_model_output": raw,
                                            "parsed_answer": scored["parsed_answer"],
                                            "correct": scored["correct"],
                                            "error": error,
                                        },
                                        secret=api_key,
                                    )
                                if options.limit is not None and count >= options.limit:
                                    break
                            if options.limit is not None and count >= options.limit:
                                break
                        if options.limit is not None and count >= options.limit:
                            break
                    if options.limit is not None and count >= options.limit:
                        break
                if options.limit is not None and count >= options.limit:
                    break
            if options.limit is not None and count >= options.limit:
                break
        if options.limit is not None and count >= options.limit:
            break

    for name in ("api_errors.jsonl", "model_responses.jsonl", "cases.jsonl", "answers.jsonl"):
        if not (run_dir / name).exists():
            (run_dir / name).write_text("", encoding="utf-8")
    summary = write_summary(run_dir, records, manifest)
    manifest.update(
        {
            "finished_at": utc_now(),
            "resolved_model": next(
                (record.get("resolved_model") for record in records if record.get("resolved_model")),
                None,
            ),
            "total_cases": len(records),
        }
    )
    write_json(run_dir / "manifest.json", manifest, secret=api_key)
    append_jsonl(run_dir / "trace.jsonl", summary, secret=api_key)
    return {"run_dir": str(run_dir), "manifest": manifest, "summary": summary}


__all__ = [
    "TrajectoryOptions",
    "parse_int_values",
    "parse_seed_range",
    "parse_values",
    "run_trajectory",
    "write_summary",
]
