"""Run artifact storage and summary generation.

All files written by this module are deliberately plain JSON/JSONL/Markdown so a
run can be inspected without importing the arena package.  Secret redaction is a
second line of defence; the provider client never passes a key to this module.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import shutil
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARTIFACT_NAMES = (
    "manifest.json",
    "trace.jsonl",
    "final.json",
    "submission.patch",
    "workspace.diff",
    "model_responses.jsonl",
    "api_errors.jsonl",
    "judge.stdout",
    "judge.stderr",
    "environment-events.jsonl",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip()


def repository_metadata(root: Path) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain")
    return {
        "repository_commit": commit,
        "repository_dirty": bool(dirty),
    }


def docker_version() -> str | None:
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None


def sanitize(value: Any, secret: str | None = None) -> Any:
    """Recursively remove obvious credential fields and redact the known key."""

    secret_text = secret or ""
    if isinstance(value, str):
        return value.replace(secret_text, "[REDACTED]") if secret_text else value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lower = key_text.lower().replace("-", "_")
            if lower in {
                "api_key",
                "apikey",
                "authorization",
                "access_token",
                "refresh_token",
                "hf_token",
            } or "password" in lower:
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = sanitize(item, secret_text)
        return result
    if isinstance(value, list):
        return [sanitize(item, secret_text) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, secret_text) for item in value]
    return value


def write_json(path: Path, value: Any, *, secret: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize(value, secret), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def append_jsonl(path: Path, value: Any, *, secret: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitize(value, secret), ensure_ascii=False) + "\n")


def copy_or_empty(source: Path, destination: Path, *, secret: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        if secret:
            text = source.read_text(encoding="utf-8", errors="replace")
            destination.write_text(text.replace(secret, "[REDACTED]"), encoding="utf-8")
        else:
            shutil.copyfile(source, destination)
    elif not destination.exists():
        destination.write_text("", encoding="utf-8")


def _diff_directories(original: Path, current: Path) -> str:
    import difflib

    original_files = {
        path.relative_to(original)
        for path in original.rglob("*")
        if path.is_file()
    } if original.is_dir() else set()
    current_files = {
        path.relative_to(current)
        for path in current.rglob("*")
        if path.is_file()
    } if current.is_dir() else set()
    def _read_text(path: Path) -> list[str]:
        if not path.is_file():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()

    chunks: list[str] = []
    for rel in sorted(original_files | current_files):
        before = _read_text(original / rel)
        after = _read_text(current / rel)
        if before != after:
            chunks.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"before/{rel}",
                    tofile=f"after/{rel}",
                    lineterm="",
                )
            )
    return "\n".join(chunks) + ("\n" if chunks else "")


class RunArtifacts:
    """Writer for one replayable run directory."""

    def __init__(self, root: Path, run_id: str, *, secret: str | None = None) -> None:
        self.root = Path(root) / run_id
        self.run_id = run_id
        self.secret = secret
        self.root.mkdir(parents=True, exist_ok=False)

    def path(self, name: str) -> Path:
        return self.root / name

    def write_manifest(self, manifest: Mapping[str, Any]) -> None:
        write_json(self.path("manifest.json"), dict(manifest), secret=self.secret)

    def update_manifest(self, updates: Mapping[str, Any]) -> None:
        current: dict[str, Any] = {}
        path = self.path("manifest.json")
        if path.is_file():
            current = json.loads(path.read_text(encoding="utf-8"))
        current.update(updates)
        self.write_manifest(current)

    def trace(self, record: Mapping[str, Any]) -> None:
        append_jsonl(self.path("trace.jsonl"), dict(record), secret=self.secret)

    def model_response(self, record: Mapping[str, Any]) -> None:
        append_jsonl(self.path("model_responses.jsonl"), dict(record), secret=self.secret)

    def api_error(self, record: Mapping[str, Any]) -> None:
        append_jsonl(self.path("api_errors.jsonl"), dict(record), secret=self.secret)

    def write_final(self, result: Any) -> None:
        write_json(self.path("final.json"), result, secret=self.secret)

    def collect_episode_files(self, episode_dir: Path) -> None:
        """Copy local runner artifacts into their stable public names."""

        copy_or_empty(
            episode_dir / "submission.patch", self.path("submission.patch"), secret=self.secret
        )
        copy_or_empty(episode_dir / "judge.stdout", self.path("judge.stdout"), secret=self.secret)
        copy_or_empty(episode_dir / "judge.stderr", self.path("judge.stderr"), secret=self.secret)
        copy_or_empty(
            episode_dir / "environment-events.jsonl",
            self.path("environment-events.jsonl"),
            secret=self.secret,
        )
        original = episode_dir / "original_workspace"
        workspace = episode_dir / "env" / "agent" / "workspace"
        diff = _diff_directories(original, workspace)
        if self.secret:
            diff = diff.replace(self.secret, "[REDACTED]")
        self.path("workspace.diff").write_text(diff, encoding="utf-8")

    def finalize(self, *, episode_dir: Path, final: Any, finished_at: str | None = None) -> None:
        self.collect_episode_files(episode_dir)
        for name in ("trace.jsonl", "model_responses.jsonl", "api_errors.jsonl"):
            path = self.path(name)
            if not path.exists():
                path.write_text("", encoding="utf-8")
        self.write_final(final)
        self.update_manifest({"finished_at": finished_at or utc_now()})


def manifest_defaults(
    *,
    root: Path,
    run_id: str,
    provider: str,
    api_base: str,
    requested_model: str,
    environment: str,
    difficulty: str,
    seed: int,
    sandbox: str,
    max_steps: int,
    max_tokens: int,
    temperature: float,
    request_extra: Mapping[str, Any],
    system_prompt: str,
    top_p: float | None = None,
    max_retries: int | None = None,
    max_http_attempts: int | None = None,
    provider_min_interval_seconds: float | None = None,
    agent_image_id: str | None = None,
    judge_image_id: str | None = None,
) -> dict[str, Any]:
    result = {
        "run_id": run_id,
        "started_at": utc_now(),
        "finished_at": None,
        "provider": provider,
        "api_base": api_base,
        "requested_model": requested_model,
        "resolved_model": None,
        "environment": environment,
        "difficulty": difficulty,
        "seed": seed,
        "sandbox": sandbox,
        "max_steps": max_steps,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "max_retries": max_retries,
        "max_http_attempts": max_http_attempts,
        "provider_min_interval_seconds": provider_min_interval_seconds,
        "request_extra": dict(request_extra),
        "system_prompt_sha256": sha256_text(system_prompt),
        "agent_image_id": agent_image_id,
        "judge_image_id": judge_image_id,
        "agent_image_digest": None,
        "judge_image_digest": None,
        "host_python_version": platform.python_version(),
        "docker_version": docker_version() if sandbox == "docker" else None,
    }
    result.update(repository_metadata(root))
    return result


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def summarize_run(run_dir: Path) -> tuple[Path, Path]:
    """Write ``summary.csv`` and ``summary.md`` and return their paths."""

    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    traces = _read_jsonl(run_dir / "trace.jsonl")
    turns = [row for row in traces if isinstance(row.get("turn"), int) and row.get("turn", 0) > 0]
    final: dict[str, Any] = {}
    if (run_dir / "final.json").is_file():
        try:
            loaded = json.loads((run_dir / "final.json").read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                final = loaded
        except json.JSONDecodeError:
            pass

    usage_totals: dict[str, float] = {}
    for row in turns:
        usage = row.get("usage")
        if isinstance(usage, Mapping):
            for key, value in usage.items():
                if isinstance(value, (int, float)):
                    usage_totals[key] = usage_totals.get(key, 0) + value
    rewards = [row.get("reward") for row in turns if isinstance(row.get("reward"), (int, float))]
    invalid = sum(1 for row in turns if row.get("parse_error") or row.get("parsed_action") is None)
    latency = [row.get("latency_ms") for row in turns if isinstance(row.get("latency_ms"), (int, float))]
    score = final.get("score", final.get("final_reward"))
    score_value = float(score) if isinstance(score, (int, float)) else 0.0
    output_tokens = usage_totals.get("completion_tokens", usage_totals.get("output_tokens"))
    input_tokens = usage_totals.get("prompt_tokens", usage_totals.get("input_tokens"))
    total_latency = sum(latency) if latency else 0.0
    row = {
        "run_id": manifest.get("run_id", run_dir.name),
        "provider": manifest.get("provider"),
        "requested_model": manifest.get("requested_model"),
        "resolved_model": manifest.get("resolved_model"),
        "environment": manifest.get("environment"),
        "difficulty": manifest.get("difficulty"),
        "seed": manifest.get("seed"),
        "sandbox": manifest.get("sandbox"),
        "turns": len(turns),
        "score": score,
        "pass": final.get("verdict") == "PASS",
        "invalid_action_rate": invalid / len(turns) if turns else 0.0,
        "mean_latency_ms": sum(latency) / len(latency) if latency else None,
        "total_reward": sum(rewards) if rewards else 0.0,
        "output_tokens": output_tokens,
        "input_tokens": input_tokens,
        "tool_steps": len(turns),
        "output_tokens_per_score": output_tokens / score_value if isinstance(output_tokens, (int, float)) and score_value > 0 else None,
        "tool_steps_per_score": len(turns) / score_value if score_value > 0 else None,
        "latency_per_score_ms": total_latency / score_value if score_value > 0 else None,
        "failure_mode": final.get("failure_mode"),
    }
    csv_path = run_dir / "summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)

    md_path = run_dir / "summary.md"
    lines = [
        f"# Arena run `{row['run_id']}`",
        "",
        f"- Model: `{row['requested_model']}`",
        f"- Provider: `{row['provider']}`",
        f"- Environment: `{row['environment']}` ({row['difficulty']})",
        f"- Seed: `{row['seed']}`",
        f"- Sandbox: `{row['sandbox']}`",
        f"- Verdict: `{final.get('verdict', 'UNKNOWN')}`",
        f"- Score: `{row['score']}`",
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key in (
        "turns",
        "invalid_action_rate",
        "mean_latency_ms",
        "output_tokens",
        "input_tokens",
        "tool_steps",
        "output_tokens_per_score",
        "tool_steps_per_score",
        "latency_per_score_ms",
        "failure_mode",
    ):
        lines.append(f"| {key} | {row[key]} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


__all__ = [
    "ARTIFACT_NAMES",
    "RunArtifacts",
    "docker_version",
    "manifest_defaults",
    "repository_metadata",
    "sanitize",
    "sha256_text",
    "summarize_run",
    "utc_now",
]
