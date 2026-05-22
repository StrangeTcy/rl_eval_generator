#!/usr/bin/env python3
"""Inspect accumulated RoPE tool logs."""
import json
import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
if not WORKSPACE.exists():
    WORKSPACE = Path.cwd()
STATE_PATH = WORKSPACE / ".rope_tool_state.json"
LOG_DIR = WORKSPACE / "logs"
TRAIN_LOG = LOG_DIR / "train_runs.jsonl"
EVAL_LOG = LOG_DIR / "eval_runs.jsonl"
INSPECT_STYLE = "%%INSPECT_STYLE%%"


def read_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    train = read_jsonl(TRAIN_LOG)
    evals = read_jsonl(EVAL_LOG)

    if INSPECT_STYLE == "raw":
        print(json.dumps({"state": state, "train": train[-10:], "eval": evals[-5:]}, indent=2))
        return

    print("Tool state:")
    print(f"  extraction attempts: {state.get('extract_attempts', 0)}")
    print(f"  sections available: {', '.join(state.get('available_sections', [])) or 'none'}")
    if state.get("last_warning"):
        print(f"  last extraction warning: {state['last_warning']}")
    print(f"  train runs: {state.get('train_runs', 0)}")
    print(f"  eval runs: {state.get('eval_runs', 0)}")

    if train:
        print("\nRecent train diagnostics:")
        for entry in train[-5:]:
            print(f"  #{entry['run']} {entry['config']}: {entry['status']} {entry.get('category', '')} max_error={entry.get('max_error', 0):.6f}")
    if evals:
        last = evals[-1]
        print("\nLast local eval:")
        print(json.dumps(last, indent=2))

    if INSPECT_STYLE == "hint":
        failures = state.get("observed_failures", [])
        if "cached_position_shift" in failures:
            print("\nSuggested next step: inspect the appendix or offset convention.")
        elif "phase_drift" in failures:
            print("\nSuggested next step: inspect the complex-form/frequency definition.")
        elif not state.get("available_sections"):
            print("\nSuggested next step: run the extraction tool and read the paper index.")


if __name__ == "__main__":
    main()
