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


# ---------------------------------------------------------------------------
# canonical event vocabulary
# ---------------------------------------------------------------------------
# Agent-side tools, the host-side episode runner, and the judge all append to an
# event log in the same shape, and nothing reads those logs at the moment they are
# written.  That is precisely why the vocabulary has to be a contract rather than a
# convention: an intervention that claims to change what an agent can observe is
# measured by comparing two trajectories, and comparing records that mean different
# things in different environments is not a measurement.
#
# The classification below is closed but never lossy.  An environment that emits an
# action nobody anticipated keeps its literal action string and lands in ``other``;
# failing or dropping unfamiliar events would quietly bias every trajectory metric
# toward the environments someone remembered to label.
#
# The hash of this file is recorded in each generated environment's manifest, so a
# run can state which vocabulary produced its labels instead of implying that the
# current checkout's does.

EVENT_SCHEMA_VERSION = 1

KINDS = (
    "observe",    # looked at something already in front of it
    "retrieve",   # asked for something not currently displayed
    "modify",     # changed workspace state
    "execute",    # ran code
    "measure",    # ran a check whose result is a pass/fail or a number
    "submit",     # ended the episode
    "judge",      # emitted by the trusted judge process, never by the agent
    "lifecycle",  # the environment itself: reset, and later any declared mutation
    "other",      # real event, unclassified action verb
)

# Ordered, matched against the leading token.  The order carries meaning where a name
# could belong to two kinds: a "run_visible_tests" is a measurement (see
# classify_action), and "apply_patch" is a modification even though the file it touches
# is a script.
_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("submit", ("submit", "finish", "finalise", "finalize", "answer")),
    ("measure", ("test", "eval", "probe", "check", "valid", "verify", "score", "metric")),
    ("execute", ("run", "train", "exec", "bash", "shell", "python", "build", "install", "fit")),
    ("modify", ("edit", "write", "patch", "replace", "insert", "delete", "remove",
                "create", "revert", "undo", "format", "add", "apply", "save", "set")),
    ("retrieve", ("search", "grep", "find", "query", "lookup", "list", "glob")),
    ("observe", ("read", "cat", "show", "view", "inspect", "open", "print", "progress",
                 "diff", "status", "head", "tail", "log", "list_logs")),
)


def _tokens(text: str) -> list[str]:
    return [part for part in "".join(
        char if char.isalnum() else " " for char in str(text or "").lower()
    ).split(" ") if part]


def _matches(token: str, verbs: tuple[str, ...]) -> bool:
    return any(token == verb or token.startswith(verb) for verb in verbs)


def classify_action(action: str, tool: str = "") -> str:
    """Map a free-form action verb onto the canonical kind, or ``other``.

    Matching is on the leading token, so ``train``, ``run_train`` and ``train_once_v2``
    agree without every environment aliasing its own tool names.  One explicit
    exception: a run-style action whose object is a test or an evaluation is a
    *measurement*, because "did it run the checks it was given" is the question the
    trajectory gates actually ask, and the leading verb alone would answer it with
    "it executed something".
    """
    if str(tool or "") == "judge":
        return "judge"
    tokens = _tokens(action)
    if not tokens:
        return "other"
    if _matches(tokens[0], _KIND_RULES[2][1]):  # leading token is run/execute-style
        if any(_matches(token, _KIND_RULES[1][1]) for token in tokens[1:]):
            return "measure"
    for kind, verbs in _KIND_RULES:
        if _matches(tokens[0], verbs):
            return kind
    return "other"


def event(action: str, *, tool: str = "agent", status: str = "ok", summary: str = "",
          **details: Any) -> dict[str, Any]:
    """Build one canonical record without writing it."""
    return {
        "ts": round(time.time(), 3),
        "tool": tool,
        "action": action,
        "status": status,
        "summary": summary,
        "kind": classify_action(action, tool),
        "schema": EVENT_SCHEMA_VERSION,
        "details": details,
    }


def read_events(path: Path | None = None) -> list[dict[str, Any]]:
    """Every recorded event, oldest first, with unparseable lines reported not dropped."""
    target = path or EVENT_LOG
    events: list[dict[str, Any]] = []
    if not target.exists():
        return events
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            record = {"action": "unparseable", "kind": "other", "schema": 0,
                      "status": "error", "summary": line[:200]}
        if isinstance(record, dict):
            events.append(record)
    return events
