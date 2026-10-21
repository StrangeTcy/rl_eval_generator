# Recursive gluing live dispatch paused on a six-request HTTP budget

Date: 2026-10-21. Companion to
`docs/reports/2026-10-20-recursive-gluing-eval.md`.

Run: [39580706886](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/39580706886),
`Recursive gluing frontier evaluation` at `7b9b5af`, dispatch
`scope=diagnostic`, `execution_mode=live`, `provider=synapse_garden`,
`model=openai/gpt-6.1-sol`, `shard 0/1`.

## What happened

| Step | Result |
| --- | --- |
| Plan (provider-free) | pass, exit 0 |
| Gates (provider-free) | pass, 94 s, 18/18 instances certified |
| Live evaluation | **fail, exit 3 after 91 s** |
| Report | ran, wrote `report/{results.json,results.csv,summary.md}` |

The job annotation was `.github#86`: *"the controller paused or failed with exit
code 3; see `runs/recursive_gluing_study/suite_checkpoint.json`
pause_reason"*. Exit 3 is the controller's **paused** code, not a study error
(which is exit 2), so the gate was fine and a ceiling or a provider failure
stopped the paid leg.

The uploaded artifacts could not be downloaded from this sandbox (the artifact
and log endpoints redirect to hosts outside the allow-list), so the root cause
below is established from the code path, the step timings, and a provider-free
reproduction — not from the checkpoint text itself. The report changes in this
change set exist so the next pause states its own reason in the artifact.

## Root cause

`tools/recursive_gluing_study.py` pinned

```python
DEFAULT_FIRST_CLASS_PROVIDER_HTTP_ATTEMPTS = 6
```

and forwarded it as the controller's `--max-http-attempts` for `yepapi` and
`synapse_garden`. That parameter is not a per-call retry cap: `tools/run_suite.py`
counts **every physical request in the dispatch** against one global budget, and
`arena/providers.py` raises `Provider HTTP attempt budget exhausted` as soon as
the counter is spent. The episode is then recorded as `paused_provider_error`,
`pause_reason` becomes `provider_error`, and the study exits 3.

The diagnostic plan declares 18 cases and 1,296 worst-case logical calls. Six
physical attempts is therefore not a "bounded first live attempt"; it is a
guaranteed pause inside the first episode, and it is invisible to the plan: the
provider-free plan never modelled the parameter and the workflow exposed no
input for it.

The observed 91 s live step matches six real model calls of roughly 15 s each.
For comparison, a rejected credential fails on the first request within a couple
of seconds, and a missing secret fails before any request (exit 2). An early
`401` is not excluded by this evidence, which is exactly why the pause reason is
now written into the report and the job summary.

## What changed

`tools/recursive_gluing_study.py`

* `derived_http_attempts(max_api_calls, max_retries) = max_api_calls × (1 + max_retries)`.
  The default budget is derived from the operator's own declared logical ceiling
  for **every** provider; there is no provider-specific small number.
* `build_plan` records `limits.max_http_attempts`,
  `limits.max_http_attempts_source` (`derived` / `explicit`),
  `worst_case.http_attempts`, and refuses (exit 2 via `StudyError`) any plan whose
  budget is below the planned logical call count. The plan prints the number
  before the first call.
* `run_study` takes the budget from the manifest's recorded plan and refuses to
  construct the controller if an explicit value would pause the leg.
* `report` now records `run.paused`, `run.pause_reason`,
  `run.recorded_case_count`, `run.paused_case_errors`, and `summary.md` opens
  with a `PAUSED (...)` block naming the pause reason and every row that never
  became a score, with the controller's own error text.

`tools/recursive_gluing_study.py plan|run` also accepts `--max-http-attempts`
and `--max-retries`; an explicit value is forwarded verbatim and never raised.

The workflow does not need to change for the fix to take effect: the live step
resumes the gate checkpoint and the report step already prints
`report/summary.md` into the job summary, which now opens with the pause block.

An optional follow-up (not in this change set — the automation token here has no
`workflows` permission) is to expose `max_http_attempts` as a
`workflow_dispatch` input alongside `max_api_calls`, and add a line for it in the
plan summary block. Until then, an explicit physical budget is only reachable
from the CLI, and the derived one is what a dispatch uses.

## Verification (provider-free)

| Command | Result |
| --- | --- |
| `python tools/recursive_gluing_study.py plan --scope diagnostic --execution-mode live --provider synapse_garden --model openai/gpt-6.1-sol` | exit 0; 18 cases; `max_http_attempts: 8000` (derived, 2000 × 4) vs 1,296 planned calls; every check `ok` |
| `python tools/recursive_gluing_study.py plan ... --max-http-attempts 6` | exit 2, `max_http_attempts` check names the pause it would cause |
| `python -m pytest tests/test_recursive_gluing_study.py -q` | 21 passed |

The diagnostic dispatch is unchanged in every declared ceiling: 2,000 calls /
8,000,000 tokens / 14,400 s, and the gate still runs before any provider access.
Only the previously undeclared physical-request budget moved from 6 to a value
the plan itself requires.

## Still open

The pause reason for run 39580706886 was never read from its artifact. To
confirm the diagnosis, re-dispatch the same scope/provider/model with
`execution_mode=live`; if the leg now pauses again, the new `summary.md` and job
summary will name the reason (`provider_error` with the controller's error text
distinguishes a rejected credential from any budget). No automatic retry, no
ceiling raise, and no re-arming were added by this change.
