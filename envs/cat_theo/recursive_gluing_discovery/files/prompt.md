# Recursive constraint grammar

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one grammar, a dict with these keys:

- `root`: module type of the outermost occurrence (a string).
- `depth`: a positive integer. The root occurrence has this remaining depth.
- `modules`: mapping from type name to a spec.
  - Every spec has `kind` (`"leaf"` or `"branch"`), `ports` (`["enter", "leave"]`),
    and `ports_domain` (the finite list of local labels for those ports).
  - A leaf spec also has `pairs`: a list of `[enter, leave]` labels allowed at
    that type. Labels are local to the type.
  - A branch spec has no pair table of its own.
- `productions`: for each branch type, two expansion rules.
  - `deeper` is used when remaining depth is at least 2. Both children are
    themselves branch occurrences with remaining depth minus one.
  - `depth_1` is used when remaining depth is 1. Both children are leaves
    (remaining depth 0).
  - Each rule names `left` and `right` child types and a `wiring` of three
    pair tables:
    - `enter`: `[parent_enter, left_enter]`
    - `mid`: `[left_leave, right_enter]`
    - `leave`: `[right_leave, parent_leave]`
    A listed pair is an allowed joint state of those two ports.
- `closing`: `null`, or `{"pairs": [[enter, leave], ...]}` extra restrictions
  on the root occurrence's ports.

The same productions are reused at every remaining depth. Nested occurrences
are not listed. Different types may use different labels.

## Output

Return a compact certificate:

```python
{
  "status": "sat",  # or "unsat"
  "realizable": {
      type_name: {
          remaining_depth: [[enter, leave], ...]
      }
  },
  "root_enter": label,  # required when status is sat
  "root_leave": label,
}
```

`realizable[t][k]` is the complete list of `(enter, leave)` pairs a module of
type `t` can realise when it has remaining depth `k`, using the productions
above, **before** applying `closing`. Leaf types are reported at depth `"0"`.
Branch types are reported at every remaining depth from `"1"` through
`str(depth)`. Pair lists may be given in any order.

If `closing` is `null`, the grammar is satisfiable when the root type at
`depth` has at least one realisable pair. If `closing` is present, it is
satisfiable when at least one of those pairs also appears in `closing["pairs"]`.
On a satisfiable instance, `root_enter` / `root_leave` must be one such pair.
On an unsatisfiable instance return `"unsat"` and still report every
`realizable` entry. A crash, timeout, or parse failure is not evidence that
the grammar is unsatisfiable.

`solve` must be deterministic: two calls on the same grammar return equal
results.

## What "correct" means

Every listed leaf table can be nonempty, and every wiring table can be
nonempty, while the assembled grammar still has no root pair that meets
`closing`. Copying a leaf table onto a branch type is not enough: child types
have their own labels, and the wiring tables are the only transport between
them. The certificate is about types and remaining depths, not about each
unfolded copy.

## Visible checks

```bash
python visible_tests.py
```
