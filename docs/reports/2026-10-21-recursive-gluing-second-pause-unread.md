# Recursive gluing: a second live pause that no artifact could explain

Date: 2026-10-21. Companion to
`docs/reports/2026-10-21-recursive-gluing-paused-http-attempt-budget.md` and
`docs/reports/2026-10-20-recursive-gluing-eval.md`.

Run: [39586680263](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/39586680263),
`Recursive gluing frontier evaluation`, dispatch on `main` at `69018581`
(the commit that carried the HTTP-attempt-budget fix),
`scope=diagnostic`, `execution_mode=live`, `provider=synapse_garden`,
`model=openai/gpt-6.1-sol`, `shard 0/1` (from the artifact name
`recursive-gluing-results-diagnostic-synapse_garden-shard0-39586680263`).

This is the confirmation dispatch the previous report asked for. It paused the
same way, and its cause is still unread.

## What happened

| Step | Result |
| --- | --- |
| Plan (provider-free) | pass, exit 0 |
| Gates (provider-free) | pass, 82 s |
| Live evaluation | **fail, exit 3 after 85 s** |
| Report | ran, wrote `report/{results.json,results.csv,summary.md}` |
| Upload plan / results | 6.1 KB / 33.4 KB |

The job annotation was again `.github#86`: *"the controller paused or failed
with exit code 3; see `runs/recursive_gluing_study/suite_checkpoint.json
pause_reason`"*. Exit 3 is the controller's paused code (a study error is exit
2), so the gate was fine and the paid leg stopped on a ceiling, a provider
failure, or a harness failure.

## What this run does and does not establish

It **does** establish that the previous diagnosis was incomplete. Run
39580706886 had a six-request physical-attempt budget; this dispatch derived
8,000 for the same case list, so the fixed backstop cannot be what stopped it
this time. The previous report's own reasoning was that six calls of ~15 s
produced the 91 s live step; this leg stopped after 85 s with that budget
raised, so *duration alone never identified the budget*. The earlier fix is
still correct on its own terms - a six-request global budget is a guaranteed
mid-episode pause - but it was not, by itself, the explanation.

It **does not** establish the actual pause reason. The checkpoint, the report,
and the step logs all live behind artifact and log endpoints that redirect to
`*.blob.core.windows.net` and `results-receiver.actions.githubusercontent.com`;
both hosts are refused from this environment (`SSL_ERROR_SYSCALL`), so the
`pause_reason`, the paused row's `error`, and the controller's own text were
never read. The report step did write them into `report/summary.md` - that is
what the previous change set added - but a reader still has to download a zip to
see them.

What the timing does rule out is an immediate credential rejection: a 401 fails
on the first request within a couple of seconds, and this leg ran 85 s. What it
leaves open, in order of likelihood:

| Candidate | What would confirm it |
| --- | --- |
| `provider_error` after retries (429/5xx, quota, or timeouts) | `pause_reason=provider_error` with a provider status line in the row |
| `floor_effect` (three consecutive zero-scored cases) | three `scored` rows with score 0 and no reasoning effort |
| `infrastructure_error` (two harness/judge failures) | `infrastructure_error` rows, `failure_mode` `judge_runtime_error` etc. |

## What changed

The pause is now diagnosed where it is looked at, from the checkpoint alone,
with no provider call:

* `tools/recursive_gluing_study.py diagnose --run-out DIR [--manifest M]
  [--exit-status N] [--github] [--out pause.json]` reads
  `suite_checkpoint.json`, names one of `credential_rejected`,
  `quota_exhausted`, `rate_limited`, `model_not_served`,
  `endpoint_unreachable`, `http_attempt_budget`, `floor_effect`,
  `harness_failure`, `ceiling_reached`, `provider_error_unclassified`, or
  `no_checkpoint`, and quotes the controller's own transcript as evidence.
* Matching is done on the controller's `stdout_tail`/`stderr_tail`, never on
  this harness's generic `error` string ("provider or quota failure detected"),
  which would otherwise label every provider failure a quota failure. An
  unmatched pause stays `provider_error_unclassified` rather than being forced
  into a bucket.
* Every quoted line is length-bounded and scrubbed of credential-shaped tokens
  (`sk-...`, `Bearer ...`, `api_key=`/`token=`) before it can reach an
  annotation, because annotations are public.
* `run` itself emits `::error::` annotations (a `::warning::` for the floor
  effect, which is a study result rather than a fault) and a `::notice::` with
  the next step whenever `GITHUB_ACTIONS=true`. The runner parses a child
  process's stdout, so this needs no workflow change - which matters because
  this session's GitHub App cannot write `.github/workflows/**` (the same
  restriction documented in `docs/audits/2026-10-20-workflow-token-repair.md`).
  Annotations render on the public run page for anyone, without a login and
  without the artifact. That is the channel that was missing.
* A refused dispatch (exit 2, usually a missing or renamed secret) is annotated
  too, instead of only appearing as a red step in a log nobody fetches.
* The same reading is included in `report/results.json` under
  `run.pause_diagnosis` and in the `PAUSED` block of `report/summary.md`, so the
  durable artifact and the run page agree.
* `diagnose` remains available for a downloaded checkpoint, and reports exit 2
  as the study's own refusal path rather than the less useful "no checkpoint".

Nothing in the workflow, the plan, the gate, the ceilings or the exit codes
changed: no retry, no ceiling raise, and no resubmission of a paused case.

## Verification (provider-free)

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_recursive_gluing_study.py -q` | 31 passed (10 new: 8 diagnosis cases, the Actions-only annotation gate, and the annotated refusal path) |
| `python tools/recursive_gluing_study.py diagnose --run-out <synthetic paused checkpoint> --github` | exit 0; `::error title=Recursive gluing http_attempt_budget (provider_error)::…` plus evidence and next step; the credential-shaped token in the log is `[REDACTED]` |
| `python -m pytest tests/test_recursive_gluing_study.py -q -k workflow` | passes, including `bash -n` on every shell step and the active/example workflow equality |

No live model call was made. No ceiling, shard or gate parameter was changed.

## Still open

The pause reason for 39586680263 is still unknown. Re-dispatch the same
scope/provider/model with `execution_mode=live`; the failed step will now carry
the reason as an annotation. If it reads `credential_rejected`, the secret needs
replacing; `rate_limited`/`quota_exhausted` are account conditions, not budget
problems; `floor_effect` is a result to read rather than a fault; and
`provider_error_unclassified` means the controller's text does not name a cause
we classify, and the quoted evidence is then the whole record.
