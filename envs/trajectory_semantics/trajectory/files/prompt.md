# Trajectory-semantics secondary track: trajectory control

This is a solver-synthesis/debugging environment, separate from the direct-answer
behavioral benchmark. It is not evidence about a model's internal recurrence.

Read `task.py`. Implement `solve(spec_text, template, payload, horizon)` in
`solution.py`. Return the state after exactly `horizon` transitions as a tuple
`(template_label, payload_int)`. Horizon is a non-negative integer and may be
large. The specification is either flat relay data or an executable restricted
reflective source-template DSL; parse it as data and do not use `eval` or
`exec`.

The judge includes format-only variants, semantic-preserving relabelings,
matched horizons including 6, 30, 126, and 510, and the witness sibling made
by changing C(b) -> A(1). Do not treat the witness as a global property and do
not hard-code a single horizon. Run `python visible_tests.py`, then submit
only `solution.py`.
