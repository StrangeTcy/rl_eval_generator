#!/usr/bin/env python3
"""Run the environment's visible tests as a logged local evaluation.

Generic across environments: it runs `visible_tests.py` under pytest, records the
result to the eval log + event stream, and prints a short summary. This is a
non-hidden sanity signal; the judge's held-out evaluation is authoritative.
"""
import subprocess
import sys
import time

from tool_state import EVAL_LOG, WORKSPACE, append_jsonl, load_state, log_event, save_state


def main() -> None:
    state = load_state()
    state["eval_runs"] = state.get("eval_runs", 0) + 1
    run_id = state["eval_runs"]

    start = time.time()
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "visible_tests.py"],
                          cwd=str(WORKSPACE), capture_output=True, text=True)
    elapsed = round(time.time() - start, 3)
    status = "ok" if proc.returncode == 0 else "fail"
    out = (proc.stdout or "").strip()
    summary = out.splitlines()[-1] if out else f"pytest exited {proc.returncode}"

    entry = {"run": run_id, "status": status, "returncode": proc.returncode,
             "elapsed_s": elapsed, "summary": summary}
    append_jsonl(EVAL_LOG, entry)
    log_event("run_eval", "local_eval", status, summary, run=run_id, returncode=proc.returncode, elapsed_s=elapsed)
    save_state(state)

    print(out[-2000:] if out else summary)


if __name__ == "__main__":
    main()
