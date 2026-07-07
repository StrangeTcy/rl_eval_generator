# SQL Fixed Point Reachability Evaluation Environment

You are tasked with implementing a relational query generator in `%%MODEL_FILE%%` (`%%MODEL_CLASS%%`).

## Problem Statement

SQL is not just a declarative data retrieval language; recursive relational operations can compute fixed points over graphs and networks.

You are given an SQLite database containing two tables:
- `edges(src INTEGER, dst INTEGER)`: representing directed edges in a graph.
- `queries(start INTEGER, target INTEGER)`: representing candidate pairs to check for reachability.

Your task is to implement `get_reachability_query(self) -> str` inside `%%MODEL_CLASS%%`. The method must return a pure SQL query string that, when executed against the database, returns all rows `(start, target)` from table `queries` where `target` is reachable from `start` via one or more hops in table `edges`.

## Requirements
1. Implement `get_reachability_query(self) -> str` in `%%MODEL_CLASS%%`.
2. The returned SQL query must handle arbitrary graph topologies, including long multi-hop paths, cycles, self-loops, and disconnected components.
3. The SQL query must output exactly two columns: `start, target` for reachable pairs present in `queries`.
4. Do not perform host-language Python graph traversals or multi-step database queries; the reachability fixed point must be expressed entirely inside the single SQL query string.

## Verification
Run local visible checks:
```bash
python visible_tests.py
```
When satisfied, run your evaluation script:
```bash
./run_eval.sh
```
