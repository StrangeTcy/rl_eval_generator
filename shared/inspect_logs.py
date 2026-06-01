#!/usr/bin/env python3
"""Inspect accumulated tool/judge event logs for this environment."""
import json

from tool_state import EVAL_LOG, EVENT_LOG, TRAIN_LOG, load_state, log_event, read_jsonl


def main() -> None:
    state = load_state()
    events = read_jsonl(EVENT_LOG)
    train = read_jsonl(TRAIN_LOG)
    evals = read_jsonl(EVAL_LOG)
    log_event("inspect_logs", "inspect", "ok", "inspected logs",
              events=len(events), train_runs=len(train), eval_runs=len(evals))

    print("Tool state:")
    print(f"  train runs: {state.get('train_runs', 0)}")
    print(f"  eval runs:  {state.get('eval_runs', 0)}")
    print(f"  tool events: {len(events)}")
    if state.get("last_warning"):
        print(f"  last warning: {state['last_warning']}")
    if state.get("observed_failures"):
        print(f"  observed failures: {', '.join(map(str, state['observed_failures']))}")

    if events:
        print("\nRecent events:")
        for entry in events[-8:]:
            print(f"  {entry['tool']}:{entry['action']} {entry['status']} — {entry['summary']}")
    if train:
        print("\nRecent train diagnostics:")
        for entry in train[-5:]:
            print(f"  #{entry.get('run', '?')} {entry.get('config', '')}: {entry.get('status', '')} {entry.get('summary', '')}")
    if evals:
        print("\nLast local eval:")
        print(json.dumps(evals[-1], indent=2))


if __name__ == "__main__":
    main()
