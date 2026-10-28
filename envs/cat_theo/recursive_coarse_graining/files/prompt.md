# Integer spin tables

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

Spins are `{0, 1}`. Each named region lists `weights[L][s][R]`, a nonnegative
integer for boundary spins `L`, `R` and an internal spin `s`.

The **effective table** of a leaf is

`T[L][R] = weights[L][0][R] + weights[L][1][R]`

(exact integer addition). A `series` node with children `left` and `right` has

`T[L][R] = T_left[L][0] * T_right[0][R] + T_left[L][1] * T_right[1][R]`

(exact integer arithmetic). The instance `tree` is either a leaf or a series
of such nodes.

If `representation` is `"revealed"`, `label_perm` is a permutation `π` of
`{0,1}` applied to the **root** table by `T'[π[L]][π[R]] = T[L][R]`. In inferred
mode it is absent from the input and must be recovered from calibration.

`calibration` contains an asymmetric `probe_table` and its
`observed_probe_table` after the presentation permutation. In inferred mode,
recover that permutation and return it as `label_perm`.

A table is **stable under doubling** when composing it with itself (the same
series rule) yields the same four integers.

## Output

```python
{"table": [[T00, T01], [T10, T11]], "fixed": True or False, "label_perm": [0, 1]}
```

`fixed` must be a Boolean. In inferred mode, `label_perm` is required and must
match the calibration. Integers must match the recomputed root table exactly.
`solve` must be deterministic.

## Visible checks

```bash
python visible_tests.py
```

## Discovering effective dynamics

Each input also contains `abstraction = [tables, anchors, queries]`.
There are two deterministic transition tables on six or ten microscopic
states. Table j maps microscopic state x to tables[j][x]. The anchors give
two [microscopic_state, binary_label] constraints. No other partition is given.

Find a binary labeling q of every microstate and two binary transition
tables E such that q(tables[j][x]) = E[j][q(x)] for every x and both j.
Both binary labels must occur. Predict each query [start, word] by composing
the indicated table indices in order, returning the final binary label.

Return `"abstraction": ["quotient", q, E, predictions]`, or
`"abstraction": ["obstruction"]` if no labeling satisfies the anchors and all
transitions. Any valid quotient is accepted. A single changed microscopic
transition can destroy every such quotient. The abstraction certificate is
mandatory alongside the original table and stability answer.
