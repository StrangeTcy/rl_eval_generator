"""Shared state and event-log helpers for environment tools.

Every generated environment is stateful: agent-side tools and the judge append
structured events to a per-workspace JSONL log, and `inspect_logs.py` reads them
back. This module is env-agnostic; environment-specific tools layer their own
state keys on top of `load_state`/`save_state`.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
if not WORKSPACE.exists():
    WORKSPACE = Path.cwd()

STATE_PATH = WORKSPACE / ".tool_state.json"
LOG_DIR = WORKSPACE / "logs"
EVENT_LOG = LOG_DIR / "events.jsonl"
TRAIN_LOG = LOG_DIR / "train_runs.jsonl"
EVAL_LOG = LOG_DIR / "eval_runs.jsonl"

DEFAULT_STATE = {
    "train_runs": 0,
    "eval_runs": 0,
    "diagnostic_runs": 0,
    "observed_failures": [],
    "last_warning": None,
}


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    else:
        state = {}
    merged = dict(DEFAULT_STATE)
    merged.update(state)
    return merged


def save_state(state: dict[str, Any]) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_event(tool: str, action: str, status: str = "ok", summary: str = "", **details: Any) -> None:
    append_jsonl(EVENT_LOG, {
        "ts": round(time.time(), 3),
        "tool": tool,
        "action": action,
        "status": status,
        "summary": summary,
        "details": details,
    })


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
