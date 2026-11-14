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
- The supported CSS subset consists of checkbox ID conditions followed by one
  output ID, separated only by `~`. Checkbox conditions may be bare IDs,
  `:checked`, or `:not(:checked)`. A bare checkbox ID matches in either state.
- The fixed DOM order applies: checkbox IDs in a chain must occur in increasing
  numeric order, without repeats. A reversed chain matches nothing.
- Declarations contain `display: block` or `display: none`. Within this subset,
  normal CSS specificity applies: compare the number of IDs, then the number
  of state pseudo-classes; the later rule wins equal-specificity ties.
- Chained conditions are conjunctions subject to sibling order. Matching
  rules with the same `display: block` declaration can express a disjunction.
  Selector lists, other combinators, classes, attributes, and `!important`
  are outside this deliberately restricted CSS subset.

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
