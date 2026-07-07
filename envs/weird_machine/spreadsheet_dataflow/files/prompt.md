# Spreadsheet Dataflow Evaluation Environment

You are tasked with implementing a spreadsheet formula generation graph in `%%MODEL_FILE%%` (`%%MODEL_CLASS%%`).

## Problem Statement

Spreadsheets are declarative dataflow computation graphs. While surface cells appear as simple tables, cell formula references encode directed acyclic dependency graphs capable of solving dynamic programming problems.

You are given a sequence length $N$. Input values (node costs) will be placed in column `A` from cell `A1` to `A{N}`.
Your goal is to implement `build_dp_formulas(self, n: int) -> dict[str, str]` inside `%%MODEL_CLASS%%`, which outputs a dictionary mapping cell identifiers in column `B` (`'B1'`, `'B2'`, ..., `'B{n}'`) to spreadsheet formula strings starting with `'='`.

### Computation Requirements
The formulas in column `B` must compute the minimum cost path to reach step $i$ where a step can advance by 1 or 2 positions:
- For $i=1$: `B1` computes the cost at cell `A1`.
- For $i=2$: `B2` computes `A2 + B1`.
- For $i \ge 3$: `Bi` computes `A{i} + MIN(B{i-1}, B{i-2})`.

## Requirements
1. Implement `build_dp_formulas(self, n: int) -> dict[str, str]` inside `%%MODEL_CLASS%%`.
2. Every returned cell value in column `B` (except optionally `B1` if assigned `=A1`) must be a valid formula string starting with `'='` (e.g., `'=A2+B1'`, `'=A3+MIN(B2, B1)'`).
3. Do not pre-calculate numeric results in Python; the dictionary values must be declarative formulas that reference cells in `A` and `B` so they evaluate correctly for any numeric inputs placed in column `A`.

## Verification
Run local visible checks:
```bash
python visible_tests.py
```
When satisfied, run your evaluation script:
```bash
./run_eval.sh
```
