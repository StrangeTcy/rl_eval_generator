# Trajectory-semantics secondary track: parse-only

This is a solver-synthesis/debugging environment, separate from the direct-answer
behavioral benchmark. It is not evidence about a model's internal recurrence.

Read `task.py`. Implement `solve(spec_text, query)` in `solution.py`.

The input is either a flat relay description or an executable restricted
reflective source-template DSL. Parse the DSL as data; do not use `eval` or
`exec`. For query `parse_only`, return the payload operation of the third rule
(the C rule before renaming): return the exact string `same` for identity,
`flip(payload)` for a flip, or the exact declared payload label for a constant
rule. Rule order defines the queried rule in both presentations. The C edit in
the broken-witness case is intentional.

Support the names and format-only comments shown in the provided task cases,
plus held-out names and combinations of identity, flip, and constant rules.
Do not hard-code only the first case. Run
`python visible_tests.py`, then submit only the changed `solution.py`.
