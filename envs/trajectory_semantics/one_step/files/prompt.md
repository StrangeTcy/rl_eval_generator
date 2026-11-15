# Trajectory-semantics secondary track: one-step control

This is a solver-synthesis/debugging environment, separate from the direct-answer
behavioral benchmark. It is not evidence about a model's internal recurrence.

Read `task.py`. Implement `solve(spec_text, template, payload)` in
`solution.py`. Return the next state as a two-item tuple `(template, payload)`
using the template labels appearing in the supplied specification. The input
and output payloads are always integers: 0 denotes the first label in the
`payloads:` declaration and 1 denotes the second, including renamed cases.
For example, with `payloads: red, blue`, emitting `blue` returns payload 1.
The specification is either flat relay data or
an executable restricted reflective source-template DSL; parse it as data and
do not use `eval` or `exec`.

The judge includes all starting states, a format-only variant, a semantic
relabeling, and both the valid and C(b) -> A(1) witness siblings. Held-out cases
use new labels, rule orderings, and three-template transition graphs, including
self-loops, with identity, flip, or constant payload operations. Follow each
rule's named source and target. Do not hard-code the public case corpus or one
starting state. Run `python visible_tests.py`, then submit only
`solution.py`.
