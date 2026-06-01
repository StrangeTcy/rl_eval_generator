#!/usr/bin/env python3
"""Run the environment's training script as a logged diagnostic.

Generic across environments: it invokes `train.py` in the workspace, records the
outcome to the train log + event stream, and prints a short summary. Use it to
get a stateful, inspectable training run before submitting.
"""
import subprocess
import sys
import time

from tool_state import TRAIN_LOG, WORKSPACE, append_jsonl, load_state, log_event, save_state


def main() -> None:
    state = load_state()
    state["train_runs"] = state.get("train_runs", 0) + 1
    run_id = state["train_runs"]

    start = time.time()
    proc = subprocess.run([sys.executable, "train.py"], cwd=str(WORKSPACE),
                          capture_output=True, text=True)
    elapsed = round(time.time() - start, 3)
    status = "ok" if proc.returncode == 0 else "fail"
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
    summary = f"train.py exited {proc.returncode} in {elapsed}s"

    entry = {"run": run_id, "config": "train.py", "status": status,
             "returncode": proc.returncode, "elapsed_s": elapsed, "summary": summary}
    if status == "fail":
        state.setdefault("observed_failures", []).append("training_failed")
        entry["last_line"] = tail[0]
    append_jsonl(TRAIN_LOG, entry)
    log_event("run_train", "diagnostic", status, summary, run=run_id, returncode=proc.returncode, elapsed_s=elapsed)
    save_state(state)

    print(summary)
    if proc.stdout.strip():
        print(proc.stdout.strip()[-1000:])
    if status == "fail" and proc.stderr.strip():
        print(proc.stderr.strip()[-1000:])


if __name__ == "__main__":
    main()
