#!/usr/bin/env python3
"""Derive trajectory metrics from an episode's event logs, and say so when it cannot.

This is the read side of the canonical event vocabulary that ``shared/tool_state.py``
writes.  It exists because the interesting question about a trajectory is not "what did
the agent finally submit" - the judge answers that - but "what did it look at, change and
run on the way", which is the only level of description that can distinguish a model that
found an invariant from one that followed a cue.

Two logs, two trust levels:

* ``environment-events.jsonl`` in the episode directory is written by the **host**.
  The agent cannot append to it, which makes it the authoritative record.
* ``agent/workspace/logs/events.jsonl`` is written by the environment's own tools,
  inside the workspace the agent controls.  It is richer - tools report what they were
  doing - and forgeable.  It is therefore used as a *claim*, and divergence between the
  two is reported rather than averaged away.

A missing host log is ``not_measurable``.  That distinction matters more than the
metrics: the self-contained ``run_eval.sh`` transport runs episodes inside containers and
does not surface an event stream at all, so an absent trajectory on that transport is
information about the transport, never a zero on a measurement of the agent.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.tool_state import KINDS, classify_action  # noqa: E402

HOST_LOG = "environment-events.jsonl"
AGENT_LOG = Path("env") / "agent" / "workspace" / "logs" / "events.jsonl"

# The gates a trajectory-sensitive evaluator would consume.  Each is a predicate on the
# derived metrics, kept here rather than inside an environment's judge so that the same
# question means the same thing in all 34 of them.  None of them is a quality judgement:
# "did it run the tests it was given" is observable, "was it a good idea" is not.
GATES = {
    "measured_before_submit": lambda m: m["counts"].get("measure", 0) > 0,
    "read_before_first_modify": lambda m: (
        m["first"]["observe"] is not None
        and (m["first"]["modify"] is None or m["first"]["observe"] < m["first"]["modify"])
    ),
    "never_modified_before_measuring": lambda m: (
        m["counts"].get("measure", 0) > 0
        and (
            m["first"]["measure"] is None
            or m["first"]["modify"] is None
            or m["first"]["measure"] < m["first"]["modify"]
        )
    ),
    "retrieved_rather_than_assumed": lambda m: m["counts"].get("retrieve", 0) > 0,
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.is_file():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            events.append({"event": "unparseable", "action_kind": "other", "schema": 0})
            continue
        if isinstance(record, dict):
            events.append(record)
    return events


def _kind(event: dict[str, Any]) -> str:
    """The event's canonical kind, recomputed if the writer predates the vocabulary."""
    kind = event.get("action_kind") or event.get("kind")
    if kind in KINDS:
        return str(kind)
    action = event.get("action")
    if isinstance(action, dict):
        return classify_action(
            str(action.get("type") or action.get("cmd") or ""), tool=str(action.get("tool") or "")
        )
    return classify_action(str(action or event.get("event") or ""))


def metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and first-occurrence indices per kind, over one ordered event list."""
    counts = Counter(_kind(event) for event in events)
    first: dict[str, int | None] = {}
    last: dict[str, int | None] = {}
    for index, event in enumerate(events):
        kind = _kind(event)
        first.setdefault(kind, index)
        last[kind] = index
    agent_actions = [event for event in events if event.get("event") == "step"]
    return {
        "events": len(events),
        "agent_actions": len(agent_actions),
        "counts": {kind: counts.get(kind, 0) for kind in KINDS},
        "first": {kind: first.get(kind) for kind in KINDS},
        "last": {kind: last.get(kind) for kind in KINDS},
        "schemas": sorted({int(event.get("schema") or 0) for event in events}),
        "uncategorized": counts.get("other", 0),
    }


def evaluate_gates(derived: dict[str, Any]) -> dict[str, bool]:
    try:
        return {name: bool(predicate(derived)) for name, predicate in GATES.items()}
    except (KeyError, TypeError):  # pragma: no cover - defensive on malformed input
        return {name: False for name in GATES}


def summarize(episode_dir: Path | str, *, include_agent_log: bool = True) -> dict[str, Any]:
    """Derive the trajectory view of one episode, or explain why there isn't one."""
    directory = Path(episode_dir)
    host_events = _read_jsonl(directory / HOST_LOG)
    if not host_events:
        return {
            "status": "not_measurable",
            "reason": "no host event log for this episode",
            "transport_note": (
                "the run_eval.sh transport scores inside containers and surfaces no "
                "event stream; only the controller path records one"
            ),
            "expected_path": str(directory / HOST_LOG),
        }
    derived = metrics(host_events)
    result: dict[str, Any] = {
        "status": "measured",
        "source": "host",
        "host": derived,
        "gates": evaluate_gates(derived),
    }
    agent_events = _read_jsonl(directory / AGENT_LOG) if include_agent_log else []
    if agent_events:
        claimed = metrics(agent_events)
        result["agent_claim"] = claimed
        result["claim_divergence"] = {
            # Not an accusation: the agent's tools only log what they were written to
            # log, so a shortfall usually means an unused tool, not a lie.  It is
            # reported because a trajectory claim that silently used the agent's own
            # count would be measuring the workspace's logging, not the behaviour.
            "host_actions_minus_claimed": derived["agent_actions"] - claimed["events"],
            "kinds_only_in_claim": sorted(
                kind for kind, value in claimed["counts"].items()
                if value and not derived["counts"].get(kind)
            ),
            "kinds_only_in_host_log": sorted(
                kind for kind, value in derived["counts"].items()
                if value and not claimed["counts"].get(kind)
            ),
        }
    elif include_agent_log:
        result["agent_claim"] = {"status": "not_measurable", "reason": "no workspace event log"}
    drifted = sorted({schema for schema in derived["schemas"] if schema} - {1})
    if drifted:
        result["schema_note"] = f"events recorded under schema {drifted}; reader is schema 1"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive trajectory metrics for one episode.")
    parser.add_argument("episode_dir", type=Path)
    parser.add_argument("--no-agent-log", action="store_true", help="ignore the forgeable workspace log")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument(
        "--require-gates",
        action="store_true",
        help="exit non-zero if the trajectory could not be measured at all",
    )
    args = parser.parse_args(argv)
    report = summarize(args.episode_dir, include_agent_log=not args.no_agent_log)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_gates and report.get("status") != "measured":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
