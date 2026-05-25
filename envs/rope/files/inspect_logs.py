#!/usr/bin/env python3
"""Inspect accumulated RoPE tool logs."""
import json

from tool_state import EVENT_LOG, EVAL_LOG, TRAIN_LOG, load_state, log_event, read_jsonl

INSPECT_STYLE = "%%INSPECT_STYLE%%"


def main():
    state = load_state()
    events = read_jsonl(EVENT_LOG)
    train = read_jsonl(TRAIN_LOG)
    evals = read_jsonl(EVAL_LOG)
    log_event("inspect_logs", "inspect", "ok", "inspected logs", events=len(events), train_runs=len(train), eval_runs=len(evals))

    if INSPECT_STYLE == "raw":
        print(json.dumps({"state": state, "events": events[-20:], "train": train[-10:], "eval": evals[-5:]}, indent=2))
        return

    print("Tool state:")
    print(f"  extraction attempts: {state.get('extract_attempts', 0)}")
    print(f"  sections available: {', '.join(state.get('available_sections', [])) or 'none'}")
    if state.get("last_warning"):
        print(f"  last extraction warning: {state['last_warning']}")
    print(f"  train runs: {state.get('train_runs', 0)}")
    print(f"  eval runs: {state.get('eval_runs', 0)}")
    print(f"  tool events: {len(events)}")

    if events:
        print("\nRecent tool events:")
        for entry in events[-8:]:
            print(f"  {entry['tool']}:{entry['action']} {entry['status']} — {entry['summary']}")
    if train:
        print("\nRecent train diagnostics:")
        for entry in train[-5:]:
            print(f"  #{entry['run']} {entry['config']}: {entry['status']} {entry.get('category', '')} max_error={entry.get('max_error', 0):.6f}")
    if evals:
        print("\nLast local eval:")
        print(json.dumps(evals[-1], indent=2))

    if INSPECT_STYLE == "hint":
        failures = state.get("observed_failures", [])
        if "cross_file_offset_propagation" in failures:
            print("\nSuggested next step: inspect how cache offsets reach the attention/RoPE call site.")
        elif "cached_position_shift" in failures:
            print("\nSuggested next step: inspect the appendix or offset convention.")
        elif "phase_drift" in failures:
            print("\nSuggested next step: inspect the complex-form/frequency definition.")
        elif not state.get("available_sections"):
            print("\nSuggested next step: run the extraction tool and read the paper index.")


if __name__ == "__main__":
    main()
