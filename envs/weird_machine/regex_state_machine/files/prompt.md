# Regex State Machine Evaluation Environment

You are tasked with implementing a string transformation engine in `%%MODEL_FILE%%` (`%%MODEL_CLASS%%`).

## Problem Statement

While regular expressions are commonly viewed as static pattern-matching rules, regex substitution systems can act as state transition machines.

Your goal is to implement one synchronous step of the Rule 110 1D cellular automaton over a binary string `state_str` consisting of characters `'0'` and `'1'`, using regular expression substitutions or transformations rather than Python character-by-character loops.

### Rule Definitions
For each cell $i$, its next state is determined by its neighborhood $b_{i-1} b_i b_{i+1}$ (with boundary cells outside the string treated as `'0'`):
- `111` -> `0`
- `110` -> `1`
- `101` -> `1`
- `100` -> `0`
- `011` -> `1`
- `010` -> `1`
- `001` -> `1`
- `000` -> `0`

## Requirements
1. Implement `step(self, state_str: str) -> str` inside `%%MODEL_CLASS%%`.
2. The output string must have the exact same length as `state_str`.
3. Do not write explicit Python character-by-character `for` or `while` loops over the string indices to compute transitions. The state transition logic should leverage regular expression matching or substitution mechanisms.

## Verification
Run local visible checks:
```bash
python visible_tests.py
```
When satisfied, run your evaluation script:
```bash
./run_eval.sh
```
