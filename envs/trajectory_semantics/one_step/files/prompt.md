# Trajectory-semantics secondary track: one-step control

This is a solver-synthesis/debugging environment, separate from the direct-answer
behavioral benchmark. It is not evidence about a model's internal recurrence.

Read `task.py`. Implement `solve(spec_text, template, payload)` in
`solution.py`. Return the next state as a two-item tuple `(template, payload)`
using the labels appearing in the supplied specification. `payload` is an
integer for the canonical cases. The specification is either flat relay data or
an executable restricted reflective source-template DSL; parse it as data and
do not use `eval` or `exec`.

The judge includes all starting states, a format-only variant, a semantic
relabeling, and both the valid and C(b) -> A(1) witness siblings. Do not
hard-code one starting state. Run `python visible_tests.py`, then submit only
`solution.py`.
