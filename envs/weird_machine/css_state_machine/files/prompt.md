# CSS State Machine & Logic Evaluation Environment

You are tasked with implementing a CSS stylesheet logic engine in `%%MODEL_FILE%%` (`%%MODEL_CLASS%%`).

## Problem Statement

While CSS is traditionally viewed as a visual presentation language, general sibling combinators (`~`) combined with pseudo-classes (`:checked`, `:not(:checked)`) form declarative constraint logic circuits capable of boolean computation without JavaScript.

You are given an HTML DOM structure with $N$ input checkboxes ordered sequentially with IDs `#c0`, `#c1`, ..., `#c{n-1}`, followed by two output container elements `#out_even` and `#out_odd` that default to `display: none;`.

Your task is to implement `generate_parity_rules(self, n: int) -> list[tuple[str, dict[str, str]]]` inside `%%MODEL_CLASS%%`. Each element in the returned list is a tuple `(selector_string, declaration_dict)`.

### Logic Specification
The stylesheet rules must compute parity over the $N$ checkbox states:
- If an **even** number of checkboxes `#c0`..`#c{n-1}` are checked (including 0), the element `#out_even` must receive `{"display": "block"}`.
- If an **odd** number of checkboxes are checked, the element `#out_odd` must receive `{"display": "block"}`.

### Selector Syntax & Semantics
Rules use general sibling combinators `~` chaining conditions from left to right. For example, for $n=2$:
- `#c0:checked ~ #c1:not(:checked) ~ #out_odd` matches `#out_odd` when `#c0` is checked and `#c1` is unchecked.
- Multiple rules targeting the same output act as logical `OR`.
- Chained conditions inside a selector act as logical `AND`.

## Requirements
1. Implement `generate_parity_rules(self, n: int) -> list[tuple[str, dict[str, str]]]` inside `%%MODEL_CLASS%%`.
2. All rules must use purely valid CSS selector strings targeting `#out_even` or `#out_odd`.
3. Do not execute procedural host logic or JavaScript; the computation must be fully embedded in the static CSS rule set.

## Verification
Run local visible checks:
```bash
python visible_tests.py
```
When satisfied, run your evaluation script:
```bash
./run_eval.sh
```
