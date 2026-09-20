"""Host-side direct-answer runner for trajectory-semantics cases."""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import append_jsonl, sanitize, sha256_text, utc_now, write_json
from .docker_backend import DockerBackend, DockerBackendError
from .providers import (
    ProviderClient,
    ProviderError,
    provider_metadata,
    resolve_api_base,
    resolve_credentials,
)
from .trajectory import certification, make_case, make_messages, public_case, score_answer
from .trajectory_plan import TrajectoryPlan, build_plan, query_horizons


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
    # Compatibility alias; new manifests call this factor system_seeds.
    semantic_seeds: list[int]
    presentation_seeds: list[int] | None = None
    system_seeds: list[int] | None = None
    initial_state_seeds: list[int] | None = None
    resource_protocol: str = "answer_only"
    api_replications: int = 1
    max_tokens: int = 64
    temperature: float = 0.0
    api_key: str | None = None
    api_key_env: str | None = None
    api_base: str | None = None
    limit: int | None = None
    judge: str = "host"
    docker_judge_image: str = "trajectory-judge:local"
    max_calls: int | None = None
    confirm_calls: int | None = None


def parse_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_values(value: str) -> list[int]:
    return [int(item) for item in parse_values(value)]


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
            raise ValueError("seed range must be ascending")
        result.extend(range(start, end + 1))
    return result


def _run_id() -> str:
    return f"trajectory-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"


def _resolved_seed_lists(options: TrajectoryOptions) -> tuple[list[int], list[int], list[int]]:
    system_seeds = list(options.system_seeds or options.semantic_seeds)
    initial_state_seeds = list(options.initial_state_seeds or [0] * len(system_seeds))
    presentation_seeds = list(
        options.presentation_seeds
        or [seed + 1_000_003 for seed in system_seeds]
    )
    if len(initial_state_seeds) != len(system_seeds):
        raise ValueError("system-seeds and initial-state-seeds must have equal lengths")
    if len(presentation_seeds) != len(system_seeds):
        raise ValueError("presentation-seeds must have one entry per system seed")
    if len(set(system_seeds)) != len(system_seeds):
        raise ValueError("system seeds must be distinct")
    if len({seed % 4 for seed in system_seeds}) != len(system_seeds):
        raise ValueError(
            "system seeds must select distinct finite relay semantics; use API replications "
            "for repeated calls to the same semantic instance"
        )
    if len(set(presentation_seeds)) != len(presentation_seeds):
        raise ValueError("presentation seeds must be distinct")
    if set(system_seeds) & set(presentation_seeds):
        raise ValueError("system and presentation seed sets must be disjoint")
    return system_seeds, initial_state_seeds, presentation_seeds


def plan_for_options(options: TrajectoryOptions) -> TrajectoryPlan:
    system_seeds, initial_state_seeds, _ = _resolved_seed_lists(options)
    return build_plan(
        system_seeds=system_seeds,
        initial_state_seeds=initial_state_seeds,
        representations=options.representations,
        witnesses=options.witnesses,
        queries=options.queries,
        horizons=options.horizons,
        relabelings=options.relabelings,
        syntax_noise=options.syntax_noise,
        api_replications=options.api_replications,
        max_tokens=options.max_tokens,
    )


def enforce_call_guard(options: TrajectoryOptions, plan: TrajectoryPlan) -> None:
    effective_calls = plan.api_call_count
    if options.limit is not None:
        if options.limit < 1:
            raise ValueError("limit must be positive")
        effective_calls = min(effective_calls, options.limit)
    if options.max_calls is not None and effective_calls > options.max_calls:
        raise ValueError(
            f"planned API calls ({effective_calls}) exceed --max-calls {options.max_calls}"
        )
    if options.confirm_calls is not None and effective_calls != options.confirm_calls:
        raise ValueError(
            f"--confirm-calls {options.confirm_calls} does not match planned API calls "
            f"({effective_calls})"
        )


def _manifest(
    options: TrajectoryOptions,
    run_id: str,
    certification_by_seed: dict[int, dict[str, object]],
    plan: TrajectoryPlan,
) -> dict[str, object]:
    api_base = resolve_api_base(options.provider, options.api_base)
    return {
        "run_id": run_id,
        "started_at": utc_now(),
        "finished_at": None,
        "benchmark_family": "trajectory_semantics",
        "track": "direct_answer_behavioral",
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
        "system_seeds": options.system_seeds,
        "initial_state_seeds": options.initial_state_seeds,
        "presentation_seeds": options.presentation_seeds,
        "resource_protocol": options.resource_protocol,
        "api_replications": options.api_replications,
        "max_output_tokens": options.max_tokens,
        "temperature": options.temperature,
        "judge": options.judge,
        "docker_judge_image": options.docker_judge_image,
        "call_plan": plan.as_dict(),
        "execution_call_limit": options.limit,
        "system_prompt_sha256": sha256_text(make_messages_placeholder(options.resource_protocol)[0]["content"]),
        "certification_by_system_seed": certification_by_seed,
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
    """Group only matched experimental conditions, never witness siblings."""

    case = record.get("case") or {}
    return tuple(
        case.get(key)
        for key in (
            "system_seed",
            "initial_state_seed",
            "representation",
            "benchmark_status",
            "witness_status_for_query",
            "query_type",
            "horizon",
            "presentation_seed",
            "relabeling",
            "syntax_noise",
            "resource_protocol",
        )
    )


def _record_key(record: dict[str, Any]) -> tuple[str, int]:
    return str(record.get("case_id") or (record.get("case") or {}).get("case_id")), int(
        record.get("api_replication", 0)
    )


def _attach_control_results(records: list[dict[str, Any]]) -> None:
    """Attach same-replication parse/one-step outcomes to trajectory records.

    A control is matched by the case's ``matched_control_id`` and API
    replication, never by a broad semantic group.  ``None`` means the control
    was not present in a truncated run; ``False`` is an observed control
    failure and must not be confused with missing data.
    """

    controls: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for record in records:
        case = record.get("case") or {}
        query_type = case.get("query_type")
        control_id = case.get("matched_control_id")
        if query_type not in {"parse_only", "one_step"} or not control_id:
            continue
        key = (str(control_id), int(record.get("api_replication", 0)))
        controls.setdefault(key, {})[str(query_type)] = record

    for record in records:
        case = record.get("case") or {}
        query_type = case.get("query_type")
        if query_type in {"parse_only", "one_step"}:
            record["parse_control_passed"] = None
            record["one_step_control_passed"] = None
            continue
        control_id = case.get("matched_control_id")
        key = (str(control_id), int(record.get("api_replication", 0)))
        matched = controls.get(key, {})
        for control_type, field in (
            ("parse_only", "parse_control_passed"),
            ("one_step", "one_step_control_passed"),
        ):
            control = matched.get(control_type)
            record[field] = bool(control.get("correct")) if control is not None else None
            record[f"{field}_case_id"] = control.get("case_id") if control is not None else None


def _control_attachments(records: list[dict[str, Any]]) -> dict[str, dict[str, object]]:
    by_control: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        case = record.get("case") or {}
        control_id = case.get("matched_control_id")
        if control_id:
            by_control.setdefault(str(control_id), []).append(record)
    attachments: dict[str, dict[str, object]] = {}
    for control_id, items in by_control.items():
        def query_stats(selected: list[dict[str, Any]]) -> dict[str, object]:
            correct = sum(bool(item.get("correct")) for item in selected)
            return {
                "n": len(selected),
                "correct": correct,
                "accuracy": correct / max(1, len(selected)),
            }

        attachments[control_id] = {
            "parse_only": query_stats(
                [item for item in items if (item.get("case") or {}).get("query_type") == "parse_only"]
            ),
            "one_step": query_stats(
                [item for item in items if (item.get("case") or {}).get("query_type") == "one_step"]
            ),
            "control_record_count": sum(
                1
                for item in items
                if (item.get("case") or {}).get("query_type") in {"parse_only", "one_step"}
            ),
        }
    return attachments


def _persist_control_fields(
    run_dir: Path,
    records: list[dict[str, Any]],
    *,
    secret: str | None = None,
) -> None:
    """Persist attached control fields on the corresponding trace records."""

    trace_path = run_dir / "trace.jsonl"
    if not trace_path.is_file():
        return
    by_key = {
        _record_key(record): record
        for record in records
        if record.get("event") == "case_result"
    }
    rewritten: list[str] = []
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            rewritten.append(line)
            continue
        if isinstance(value, dict) and value.get("event") == "case_result":
            matched = by_key.get(_record_key(value))
            if matched is not None:
                for field in (
                    "parse_control_passed",
                    "one_step_control_passed",
                    "parse_control_passed_case_id",
                    "one_step_control_passed_case_id",
                ):
                    if field in matched:
                        value[field] = matched[field]
        rewritten.append(json.dumps(sanitize(value, secret), ensure_ascii=False))
    trace_path.write_text("\n".join(rewritten) + ("\n" if rewritten else ""), encoding="utf-8")


def write_summary(
    run_dir: Path,
    records: list[dict[str, Any]],
    manifest: dict[str, object],
    *,
    secret: str | None = None,
) -> dict[str, Any]:
    _attach_control_results(records)
    _persist_control_fields(run_dir, records, secret=secret)
    groups: dict[tuple[object, ...], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(_group_key(record), []).append(record)
    attachments = _control_attachments(records)
    rows: list[dict[str, Any]] = []
    for key, items in sorted(groups.items(), key=lambda pair: str(pair[0])):
        case = items[0].get("case") or {}
        correct = sum(bool(item.get("correct")) for item in items)
        control = attachments.get(str(case.get("matched_control_id")), {})
        parse_stats = control.get("parse_only", {})
        one_step_stats = control.get("one_step", {})
        trajectory_items = [
            item
            for item in items
            if (item.get("case") or {}).get("query_type") not in {"parse_only", "one_step"}
        ]
        conditional_items = [
            item
            for item in trajectory_items
            if item.get("parse_control_passed") is True
            and item.get("one_step_control_passed") is True
        ]

        def consensus(selected: list[dict[str, Any]], field: str) -> bool | None:
            values = [item[field] for item in selected if isinstance(item.get(field), bool)]
            if not values or any(value != values[0] for value in values[1:]):
                return None
            return values[0]

        rows.append(
            {
                "system_seed": key[0],
                "initial_state_seed": key[1],
                "representation": key[2],
                "benchmark_status": key[3],
                "witness_status_for_query": key[4],
                "query_type": key[5],
                "horizon": key[6],
                "presentation_seed": key[7],
                "relabeling": key[8],
                "syntax_noise": key[9],
                "resource_protocol": key[10],
                "matched_control_id": case.get("matched_control_id"),
                "semantic_equivalence_id": case.get("semantic_equivalence_id"),
                "n": len(items),
                "correct": correct,
                "accuracy": correct / max(1, len(items)),
                "format_valid_rate": sum(bool(item.get("format_valid")) for item in items) / max(1, len(items)),
                "stale_witness_match_rate": sum(bool(item.get("matched_stale_witness_prediction")) for item in items) / max(1, len(items)),
                "parse_control_n": parse_stats.get("n", 0),
                "parse_control_accuracy": parse_stats.get("accuracy", 0.0),
                "one_step_control_n": one_step_stats.get("n", 0),
                "one_step_control_accuracy": one_step_stats.get("accuracy", 0.0),
                "parse_control_passed": consensus(trajectory_items, "parse_control_passed"),
                "one_step_control_passed": consensus(trajectory_items, "one_step_control_passed"),
                "conditional_n": len(conditional_items),
                "conditional_correct": sum(bool(item.get("correct")) for item in conditional_items),
                "conditional_accuracy": (
                    sum(bool(item.get("correct")) for item in conditional_items)
                    / max(1, len(conditional_items))
                ),
                "conditional_excluded_n": len(trajectory_items) - len(conditional_items),
            }
        )
    csv_path = run_dir / "summary.csv"
    fields = list(rows[0]) if rows else ["representation", "query_type", "accuracy"]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    trajectory_records = [
        record
        for record in records
        if (record.get("case") or {}).get("query_type") not in {"parse_only", "one_step"}
    ]
    conditional_records = [
        record
        for record in trajectory_records
        if record.get("parse_control_passed") is True
        and record.get("one_step_control_passed") is True
    ]
    summary = {
        "event": "summary",
        "track": "direct_answer_behavioral",
        "scoreboard": "trajectory_direct_answer",
        "total_cases": len(records),
        "correct": sum(bool(item.get("correct")) for item in records),
        "accuracy": sum(bool(item.get("correct")) for item in records) / max(1, len(records)),
        "group_count": len(rows),
        "groups": rows,
        "conditional_trajectory_cases": len(conditional_records),
        "conditional_trajectory_correct": sum(bool(item.get("correct")) for item in conditional_records),
        "conditional_trajectory_accuracy": (
            sum(bool(item.get("correct")) for item in conditional_records)
            / max(1, len(conditional_records))
        ),
        "excluded_trajectory_cases": len(trajectory_records) - len(conditional_records),
        "matched_control_attachments": attachments,
        "interpretation_warning": "These are behavioral intervention results, not a serial-depth measurement.",
    }
    write_json(run_dir / "summary.json", summary)
    markdown = [
        "# Trajectory-semantics summary",
        "",
        f"- Total API results: `{summary['total_cases']}`",
        f"- Accuracy: `{summary['accuracy']}`",
        "- Interpretation: behavioral sensitivity to named interventions; no internal depth claim.",
        "",
        "| system | initial | representation | benchmark | query | T | relabeling | syntax | n | accuracy | parse control | one-step control | parse passed | one-step passed | conditional n | conditional accuracy | stale match |",
        "|---:|---:|---|---|---|---:|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|",
    ]
    for row in rows:
        markdown.append(
            f"| {row['system_seed']} | {row['initial_state_seed']} | {row['representation']} | "
            f"{row['benchmark_status']} | {row['query_type']} | {row['horizon']} | "
            f"{row['relabeling']} | {row['syntax_noise']} | {row['n']} | {row['accuracy']:.3f} | "
            f"{row['parse_control_accuracy']:.3f} | {row['one_step_control_accuracy']:.3f} | "
            f"{row['parse_control_passed']} | {row['one_step_control_passed']} | "
            f"{row['conditional_n']} | {row['conditional_accuracy']:.3f} | "
            f"{row['stale_witness_match_rate']:.3f} |"
        )
    (run_dir / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return summary


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _run_docker_judge(
    run_dir: Path,
    options: TrajectoryOptions,
) -> dict[str, Any]:
    output_dir = run_dir / "docker_judge"
    output_dir.mkdir(parents=True, exist_ok=True)
    backend = DockerBackend()
    result = backend.run_trajectory_judge(
        options.docker_judge_image,
        run_dir / "cases.jsonl",
        run_dir / "answers.jsonl",
        output_dir,
    )
    (output_dir / "stdout").write_text(result.stdout, encoding="utf-8")
    (output_dir / "stderr").write_text(result.stderr, encoding="utf-8")
    docker_results = _read_jsonl(output_dir / "results.jsonl")
    return {
        "image": options.docker_judge_image,
        "returncode": result.returncode,
        "command": result.command,
        "results": docker_results,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _apply_docker_scores(
    records: list[dict[str, Any]],
    docker_report: dict[str, Any],
    *,
    require_agreement: bool,
) -> None:
    docker_by_key = {
        (str(row.get("case_id")), int(row.get("api_replication", 0))): row
        for row in docker_report.get("results", [])
    }
    disagreements: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    for record in records:
        key = _record_key(record)
        docker = docker_by_key.get(key)
        if docker is None:
            missing.append({"case_id": key[0], "api_replication": key[1]})
            continue
        host_correct = bool(record.get("correct"))
        docker_correct = bool(docker.get("correct"))
        record["host_correct"] = host_correct
        record["docker_correct"] = docker_correct
        record["docker_format_valid"] = bool(docker.get("format_valid"))
        record["docker_matched_stale_witness_prediction"] = bool(
            docker.get("matched_stale_witness_prediction")
        )
        if host_correct != docker_correct:
            disagreements.append(
                {
                    "case_id": key[0],
                    "api_replication": key[1],
                    "host_correct": host_correct,
                    "docker_correct": docker_correct,
                }
            )
        record["correct"] = docker_correct
    docker_report["disagreements"] = disagreements
    docker_report["missing"] = missing
    if docker_report.get("returncode") != 0 or missing:
        raise RuntimeError("Docker trajectory judge did not produce a complete result")
    if require_agreement and disagreements:
        raise RuntimeError("host and Docker trajectory judgments disagree")


def run_trajectory(options: TrajectoryOptions) -> dict[str, Any]:
    if options.judge not in {"host", "docker", "both"}:
        raise ValueError("judge must be host, docker, or both")
    plan = plan_for_options(options)
    enforce_call_guard(options, plan)
    system_seeds, initial_state_seeds, presentation_seeds = _resolved_seed_lists(options)
    options.system_seeds = system_seeds
    options.initial_state_seeds = initial_state_seeds
    options.presentation_seeds = presentation_seeds
    options.semantic_seeds = list(system_seeds)
    if options.api_replications < 1:
        raise ValueError("api-replications must be positive")
    api_key, _ = resolve_credentials(
        options.provider, api_key=options.api_key, api_key_env=options.api_key_env
    )
    api_base = resolve_api_base(options.provider, options.api_base)
    run_dir = Path(options.out)
    run_dir.mkdir(parents=True, exist_ok=False)
    run_id = _run_id()
    certs = {seed: certification(seed).as_dict() for seed in system_seeds}
    manifest = _manifest(options, run_id, certs, plan)
    manifest["api_base"] = api_base
    write_json(run_dir / "manifest.json", manifest, secret=api_key)
    append_jsonl(
        run_dir / "trace.jsonl",
        {"event": "reset", "run_id": run_id, "manifest": manifest},
        secret=api_key,
    )
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
    for system_seed, initial_state_seed, presentation_seed in zip(
        system_seeds, initial_state_seeds, presentation_seeds, strict=True
    ):
        cert = certs[system_seed]
        for representation in options.representations:
            for witness in options.witnesses:
                for query in options.queries:
                    for horizon in query_horizons(query, options.horizons):
                        for relabeling in options.relabelings:
                            for syntax_noise in options.syntax_noise:
                                case = make_case(
                                    system_seed=system_seed,
                                    initial_state_seed=initial_state_seed,
                                    semantic_seed=system_seed,
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
                                    error_request_id: str | None = None
                                    error_response_headers: dict[str, str] = {}
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
                                        error_request_id = exc.request_id
                                        error_response_headers = exc.response_headers
                                    record = {
                                        "event": "case_result",
                                        "case_id": case.case_id,
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
                                        "error_request_id": error_request_id,
                                        "error_response_headers": error_response_headers,
                                        "provider_attempts": [
                                            attempt.as_dict() for attempt in client.last_attempts
                                        ],
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

    docker_report: dict[str, Any] | None = None
    if options.judge in {"docker", "both"}:
        try:
            docker_report = _run_docker_judge(run_dir, options)
            _apply_docker_scores(
                records,
                docker_report,
                require_agreement=options.judge == "both",
            )
        except DockerBackendError as exc:
            docker_report = {"error": str(exc), "image": options.docker_judge_image}
            write_json(run_dir / "docker_judge.json", docker_report, secret=api_key)
            raise
        finally:
            if docker_report is not None:
                write_json(run_dir / "docker_judge.json", docker_report, secret=api_key)
    summary = write_summary(run_dir, records, manifest, secret=api_key)
    if docker_report is not None:
        summary["docker_judge"] = {
            "returncode": docker_report.get("returncode"),
            "disagreements": docker_report.get("disagreements", []),
            "missing": docker_report.get("missing", []),
        }
        write_json(run_dir / "summary.json", summary, secret=api_key)
    manifest.update(
        {
            "finished_at": utc_now(),
            "resolved_model": next(
                (record.get("resolved_model") for record in records if record.get("resolved_model")),
                None,
            ),
            "total_cases": len(records),
            "host_correct": sum(bool(record.get("host_correct", record.get("correct"))) for record in records),
            "docker_correct": (
                sum(bool(record.get("docker_correct")) for record in records)
                if docker_report is not None
                else None
            ),
        }
    )
    write_json(run_dir / "manifest.json", manifest, secret=api_key)
    append_jsonl(run_dir / "trace.jsonl", summary, secret=api_key)
    return {"run_dir": str(run_dir), "manifest": manifest, "summary": summary}


__all__ = [
    "TrajectoryOptions",
    "enforce_call_guard",
    "parse_int_values",
    "parse_seed_range",
    "parse_values",
    "plan_for_options",
    "run_trajectory",
    "write_summary",
]
