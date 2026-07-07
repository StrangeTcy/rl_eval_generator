#!/usr/bin/env python3
"""Judge for sql_fixed_point environment."""
import os
import sys
import json

from judge_lib import (base_result, emit, eval_env, judge_event, make_workdir,
                       mark_check, run, score_from_accuracy, scrub_workdir,
                       set_failure, set_metric, train_env, validate_submission,
                       require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%

def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"query_module.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, random, sqlite3, json
sys.path.insert(0, {workdir!r})
from query_module import %%MODEL_CLASS%%

engine = %%MODEL_CLASS%%()
checks = {{}}

# Reference BFS reachability
def reference_reachable(edges, start, target):
    adj = {{}}
    for u, v in edges:
        adj.setdefault(u, set()).add(v)
    visited = set()
    queue = [start]
    while queue:
        curr = queue.pop(0)
        for nxt in adj.get(curr, []):
            if nxt == target:
                return True
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
    return False

# 1. Basic SQL query structure check
try:
    query = engine.get_reachability_query()
    checks["query_is_sql"] = isinstance(query, str) and ("select" in query.lower() or "with" in query.lower())
except Exception:
    checks["query_is_sql"] = False

# 2. Cycle handling check
try:
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE edges (src INTEGER, dst INTEGER)")
    cur.execute("CREATE TABLE queries (start INTEGER, target INTEGER)")
    cur.executemany("INSERT INTO edges VALUES (?, ?)", [(1, 2), (2, 3), (3, 1)])
    cur.executemany("INSERT INTO queries VALUES (?, ?)", [(1, 3), (1, 1), (2, 1), (1, 4)])
    conn.commit()
    
    cur.execute(query)
    rows = set(cur.fetchall())
    expected = {{(1, 3), (1, 1), (2, 1)}}
    checks["cycle_handling"] = bool(rows == expected)
    conn.close()
except Exception:
    checks["cycle_handling"] = False

# 3. Randomized complex graph reachability seeded by JUDGE_SEED
try:
    rng = random.Random(%%JUDGE_SEED%%)
    chain_len = int("%%CHAIN_LEN%%")
    
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE edges (src INTEGER, dst INTEGER)")
    cur.execute("CREATE TABLE queries (start INTEGER, target INTEGER)")
    
    edges = []
    # Build a chain of length chain_len
    for i in range(1, chain_len):
        edges.append((i, i + 1))
    # Add some random shortcut edges and cycles
    nodes = list(range(1, chain_len + 1))
    for _ in range(chain_len // 2):
        u, v = rng.choice(nodes), rng.choice(nodes)
        if u != v:
            edges.append((u, v))
            
    # Create random queries
    queries = []
    for _ in range(20):
        u, v = rng.choice(nodes), rng.choice(nodes)
        queries.append((u, v))
        
    cur.executemany("INSERT INTO edges VALUES (?, ?)", edges)
    cur.executemany("INSERT INTO queries VALUES (?, ?)", queries)
    conn.commit()
    
    cur.execute(query)
    rows = set(cur.fetchall())
    
    expected = set()
    for u, v in queries:
        if reference_reachable(edges, u, v):
            expected.add((u, v))
            
    checks["randomized_reachability"] = bool(rows == expected)
    conn.close()
except Exception as e:
    checks["randomized_reachability"] = False

with open("eval_outputs.json", "w") as f_out:
    json.dump(checks, f_out)
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        with open(os.path.join(workdir, "eval_outputs.json"), "r", encoding="utf-8") as f_in:
            checks = json.load(f_in)
        sql_ok = bool(checks.get("query_is_sql", False))
        cyc_ok = bool(checks.get("cycle_handling", False))
        rand_ok = bool(checks.get("randomized_reachability", False))

        mark_check(result, "query_is_sql", sql_ok)
        mark_check(result, "cycle_handling", cyc_ok)
        mark_check(result, "randomized_reachability", rand_ok)

        passed = sum([sql_ok, cyc_ok, rand_ok])
        accuracy = passed / 3.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
