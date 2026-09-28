# Trajectory-semantics secondary track: parse-only

This is a solver-synthesis/debugging environment, separate from the direct-answer
behavioral benchmark. It is not evidence about a model's internal recurrence.

Read `task.py`. Implement `solve(spec_text, query)` in `solution.py`.

The input is either a flat relay description or an executable restricted
reflective source-template DSL. Parse the DSL as data; do not use `eval` or
`exec`. For query `parse_only`, return the payload operation of the C rule:
return the exact string `same` for identity or the exact payload label for a
constant rule. The C edit in the broken-witness case is intentional.

Support the semantic-preserving names and format-only comments shown in the
provided task cases. Do not hard-code only the first case. Run
`python visible_tests.py`, then submit only the changed `solution.py`.
