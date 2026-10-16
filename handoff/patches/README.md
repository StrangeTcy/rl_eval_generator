# `run_suite.py`: diagnose the infrastructure failure before deciding how to survive it

State: **one edit, 8 inserted lines, 0 deleted.** Verified on `main`'s tree (`774c47b`):
`py_compile` OK, and `tests/test_exhaustive_campaign_recovery.py` — the file that encodes the
retry-ledger contract — passes 5/5.

Price, measured with `tools/campaign_rearm.py --check-rebase-target … --check-rebase-against …`:
**costly**, re-grading the exact-instance gate over **1 verdict file** (`tools/run_suite.py`),
against both Mercury's pin `774c47b` and Atria's pin `3d6e743`.

## Why this and not the ledger change

An earlier draft of this patch stopped charging a case's retry when the failure looked systemic.
It was wrong, and the repository's own tests said so in one run: three tests
(`test_independent_episode_timeout_is_a_bounded_infrastructure_retry`,
`test_container_failure_is_automatically_retried_then_stops_at_its_bound`,
`test_one_poisoned_case_cannot_hold_the_rest_of_the_plan_hostage`) assert that the case **is**
charged, because charging is what bounds a case that is genuinely poisoned. Relaxing that trades
a bounded loop for an unbounded one.

The honest reading is that the discriminator I invented is not knowable from the branch that
produces it. `arena controller did not return a scored result` covers a container that died on one
case and a provider that answered nobody, and those want opposite responses. So this patch stops
guessing and records what the episode said: exit code, and redacted tails of stderr and stdout,
for every `infrastructure_error` row. The next failure names its own cause.

Evidence that the distinction is live, from the provider console on 2026-10-16 while the campaign
was pausing with `infrastructure_error`: Mercury's requests are `v1/chat/completions`
`mercury-2.5` **SUCCESS** at 03:03:52, 03:26:53, 03:49:51 and 08:03:34 — roughly one successful
call per leg, 23 minutes apart, each followed by a paused leg that banked nothing.

## The edit

In `tools/run_suite.py`, find the end of the `result = { … }` literal built for an infrastructure
failure — it ends with these three lines at 12-space indentation:

```python
                "stdout_tail": stdout,
                "stderr_tail": stderr,
            }
```

and insert directly after the closing brace:

```python
            # The message above is a *class*, and the class is ambiguous: a container that died
            # on one case and a provider that answered nobody look identical from here, yet they
            # call for opposite responses - bound the case, or wait for the harness. Preserve what
            # the episode actually said, so the distinction is made on evidence instead of guessed.
            # Agent-free and redacted: this field rides the state artifact and the status comment.
            result["harness_returncode"] = process.returncode
            result["harness_stderr_tail"] = _redact(process.stderr or "", secret)[-400:]
            result["harness_stdout_tail"] = _redact(process.stdout or "", secret)[-400:]
```

Verification on the commit page: **1 file changed, 8 insertions(+), 0 deletions(-)**.

`run-suite-diagnose-infrastructure-failure.diff` is the same edit as a patch, and
`run_suite.py.diagnosed` is the whole file for a paste.

## What it does not do

It changes no behaviour: every branch, bound and pause reason is exactly as before, so it cannot
make a campaign bank a row. It makes the *next* decision evidence-based. Applying it costs the gate
re-grade, so it is worth riding a re-pin that is happening for another reason rather than paying for
it alone.
