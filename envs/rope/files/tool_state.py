"""Shared state and event-log helpers for RoPE tools."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
if not WORKSPACE.exists():
    WORKSPACE = Path.cwd()

STATE_PATH = WORKSPACE / ".rope_tool_state.json"
LOG_DIR = WORKSPACE / "logs"
EVENT_LOG = LOG_DIR / "events.jsonl"
TRAIN_LOG = LOG_DIR / "train_runs.jsonl"
EVAL_LOG = LOG_DIR / "eval_runs.jsonl"

DEFAULT_STATE = {
    "extract_attempts": 0,
    "available_sections": [],
    "missing_sections": [],
    "last_warning": None,
    "diagnostic_runs": 0,
    "eval_runs": 0,
    "train_runs": 0,
    "observed_failures": [],
}


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = {}
    merged = dict(DEFAULT_STATE)
    merged.update(state)
    return merged


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_event(tool: str, action: str, status: str = "ok", summary: str = "", **details: Any) -> None:
    entry = {
        "ts": round(time.time(), 3),
        "tool": tool,
        "action": action,
        "status": status,
        "summary": summary,
        "details": details,
    }
    append_jsonl(EVENT_LOG, entry)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
