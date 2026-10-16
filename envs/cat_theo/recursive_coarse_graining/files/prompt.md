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
`{0,1}` applied to the **root** table by `T'[π[L]][π[R]] = T[L][R]`. If it is
absent, `π` is the identity.

A table is a **doubling fixed point** when composing it with itself (the same
series rule) yields the same four integers.

## Output

```python
{"table": [[T00, T01], [T10, T11]], "fixed": True or False}
```

`fixed` must be a Boolean. Integers must match the recomputed root table
exactly. `solve` must be deterministic.

## Visible checks

```bash
python visible_tests.py
```
