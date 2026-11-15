# Boolean-Selector Logic Evaluation Environment

Implement a static Boolean-selector rule generator in `%%MODEL_FILE%%` (`%%MODEL_CLASS%%`). This is a guided construction task in a closed language inspired by CSS selector notation.

## Problem Statement

The evaluator implements the Boolean-selector language defined below. Scores concern parity in this language; browser rendering, DOM relationships, and CSS specificity are outside this environment.

There are $N$ Boolean inputs named `#c0`, `#c1`, ..., `#c{n-1}` and two outputs named `#out_even` and `#out_odd`, initially `display: none`.

Your task is to implement `generate_parity_rules(self, n: int) -> list[tuple[str, dict[str, str]]]` inside `%%MODEL_CLASS%%`. Each element in the returned list is a tuple `(selector_string, declaration_dict)`.

### Logic Specification
The rules must compute parity over the $N$ checkbox states:
- If an **even** number of checkboxes `#c0`..`#c{n-1}` are checked (including 0), the element `#out_even` must receive `{"display": "block"}`.
- If an **odd** number of checkboxes are checked, the element `#out_odd` must receive `{"display": "block"}`.

### Selector Syntax & Semantics
Each selector contains one or more input conditions separated by `~`, followed by one output. A condition is exactly `#cK`, `#cK:checked`, or `#cK:not(:checked)`, with `0 <= K < N`. Whitespace may surround the `~` separators. A bare `#cK` is unconditional, `:checked` requires a true input, and `:not(:checked)` requires a false input. For example, for $n=2$:
- `#c0:checked ~ #c1:not(:checked) ~ #out_odd` matches `#out_odd` when `#c0` is checked and `#c1` is unchecked.
- Chained conditions act as logical `AND`. Their order is immaterial: reversing input conditions preserves their meaning.
- A declaration must contain exactly `display`, with value `block` or `none`. Matching rules execute in their returned order; the last matching rule sets the output. There is no specificity ranking.
- A rule with a contradictory conjunction never matches. Unknown inputs, extra selector syntax, and extra declaration properties are rejected.
- Multiple rules that only set `block` implement logical `OR` because the initial output is `none`.

## Requirements
1. Implement `generate_parity_rules(self, n: int) -> list[tuple[str, dict[str, str]]]` inside `%%MODEL_CLASS%%`.
2. All rules must follow the closed Boolean-selector grammar and target `#out_even` or `#out_odd`.
3. Runtime parity computation must be fully embedded in the returned static rules. Host code may generate those rules from `n`.

## Verification
Run local visible checks:
```bash
python visible_tests.py
```
When satisfied, run your evaluation script:
```bash
./run_eval.sh
```
