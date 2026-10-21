# Recursive gluing frontier evaluation (manual dispatch)

This directory holds the copyable workflow source. GitHub executes only
`.github/workflows/recursive-gluing-eval.yml`; it does not execute the docs copy.
The updated workflow is intentionally staged here so it can be copied into
`.github/workflows/` by a maintainer with the required repository permission.

| File | Role |
| --- | --- |
| `docs/workflows/recursive-gluing-eval.yml.example` | Copyable updated workflow: one `workflow_dispatch`, no schedule, one provider/model pair per dispatch. |
| `tools/recursive_gluing_study.py` | `plan` / `run` / `report` for the study. Builds a filtered manifest and a provider-free budget plan, forwards `live` to `tools/run_suite.py`, and turns the checkpoint into JSON + CSV + Markdown. |
| `tools/recursive_references.py` | Host-side correct/wrong patch pairs for the exact-instance gate. Never part of the agent-facing tree. |
| `docs/decisions/2026-10-16-sheaf-recursive-reasoning.md` | Why the family exists and what the diagnostic matrix is testing. |

## What one dispatch does

1. **Plan (provider-free).** `plan` builds the manifest for the requested
   `scope`/`matrix`/`seeds`/shard and checks every ceiling *before* anything is
   generated or called. A plan that does not fit exits non-zero, so a dispatch
   can never authorise more spend than it declared. The plan is uploaded as an
   artifact and written to the job summary (case count + worst-case arithmetic).
2. **Gate (provider-free).** `run --execution-mode gates_only` generates each
   requested case once and grades three patches against its real judge: an empty
   no-op must score 0, a plausible-but-wrong patch must fail the named held-out
   check, and the reference must pass. Any case that does not discriminate is
   reported in `instance_oracles.json` and the step fails. **No provider call is
   made in this step**, whatever the dispatch says.
3. **Live (`execution_mode=live` only).** The same gate is re-checked from the
   checkpoint (rows are reused), then the suite runs with the operator's
   ceilings. A quota/auth failure pauses the run instead of retrying; ceilings
   are never raised automatically; an unrecorded case stays unrecorded rather
   than being counted as a scored zero or as `unsat`.
4. **Report (always).** JSON, CSV and Markdown per environment and per factor,
   with every case's outcome class, hidden-check breakdown, usage and latency.

## Budget arithmetic (what a plan prints)

| Dispatch | Cases | Worst-case API calls | Worst-case output tokens | Wall estimate |
| --- | --- | --- | --- | --- |
| `scope=diagnostic` (defaults `max_steps=24`, `max_tokens=4096`) | 18 | 1296 | 5,308,416 | 14,400 s |
| `scope=family matrix=pairwise` (all certified members) | 76 | 5,472 | 22,413,312 | 49,200 s → needs 4 shards |

The wall estimate is a *ceiling*, not a forecast: `cases × 600 s + 3600 s` of
gate reserve. A GitHub job may run at most six hours, so a family run that does
not fit is split with `shard_count` (each dispatch takes one `shard_index`); the
shards partition the sorted case list round-robin and are disjoint by
construction. Four shards of the pairwise design are 19 cases / 15,000 s each.

## Deployment status

The default branch currently has an older workflow file, but it lacks this
study's implementation and AgentRouter option. This updated source is staged at
`docs/workflows/recursive-gluing-eval.yml.example`; copy it over the existing
file at `.github/workflows/recursive-gluing-eval.yml` before dispatching the
updated study:

```bash
cp docs/workflows/recursive-gluing-eval.yml.example .github/workflows/recursive-gluing-eval.yml
```

The code and docs source are on the study branch. After the copy is committed,
select that branch/ref in the Actions UI (or pass it with `gh workflow run --ref ...`).

## Provider selection

Every dispatch records an explicit provider and exact model ID. `agentrouter` is
the intended provider and the workflow defaults to it; it uses AgentRouter's
OpenAI-compatible Chat Completions endpoint at
`https://agentrouter.org/v1`. For a live run, configure the repository
Actions secret `AGENTROUTER_API_KEY` (the controller also accepts the documented
aliases `AGENT_ROUTER_API_KEY` and `AGENTROUTER_API_TOKEN`). The model field must
be an exact AgentRouter model ID (for example, `gpt-6-astra`); its roster is
dynamic, so check the [current AgentRouter model list](https://agentrouter.org/docs/claude-code.html)
before a live run. The evaluator does not resolve catalogues or aliases.
`plan_only` does not require a secret and makes no provider calls. Other
providers remain selectable, but only choose them when they are the intended
experiment condition.

## Dispatching

```bash
# 1. Plan only. No model call is possible in this mode.
gh workflow run recursive-gluing-eval.yml --ref <published-branch> \
  -f scope=diagnostic -f execution_mode=plan_only \
  -f provider=agentrouter -f model=gpt-6-astra -f wire_api=chat_completions

# 2. Read the plan artifact and the job summary: case count, expected calls and
#    tokens, and whether the declared ceilings hold.
gh run list --workflow recursive-gluing-eval.yml --limit 1
gh run download <run-id> -n recursive-gluing-plan-diagnostic-<run-id>

# 3. Live. The gate runs first, in the same step chain, and stops the dispatch
#    before provider access if it fails.
gh workflow run recursive-gluing-eval.yml --ref <published-branch> \
  -f scope=diagnostic -f execution_mode=live \
  -f provider=agentrouter -f model=gpt-6-astra -f wire_api=chat_completions \
  -f max_api_calls=2000 -f max_tokens_total=8000000 -f max_wall_seconds=14400
```

Results: `gh run download <run-id> -n recursive-gluing-results-diagnostic-agentrouter-shard0-<run-id>`
gives `runs/recursive_gluing_study/` (checkpoint, `instance_oracles.json`,
`oracle_preflight.json`, per-case directories with `final.json`,
`result_record.json`, `model_responses.jsonl`, `submission.patch`) plus
`report/results.json`, `report/results.csv` and `report/summary.md`.

## Whole-family rerun

`scope=family` defaults to `matrix=pairwise` (strength-2 over every axis pair of
every certified member). Because 76 cases cannot fit a six-hour job, dispatch one
shard at a time:

```bash
for i in 0 1 2 3; do
  gh workflow run recursive-gluing-eval.yml --ref <published-branch> \
    -f scope=family -f matrix=pairwise -f execution_mode=live \
    -f provider=agentrouter -f model=gpt-6-astra -f wire_api=chat_completions \
    -f shard_index=$i -f shard_count=4 \
    -f max_api_calls=2000 -f max_tokens_total=8000000 -f max_wall_seconds=14400
done
```

Each shard is a separate artifact; `report --run-out <dir>` accepts one entry per
shard and merges them (`shards` and `conflicting_case_ids` are recorded). A case
graded twice is reported, not silently averaged.

## Coverage the study refuses

* `recursive_holonomy_gluing` is **excluded** from live scored evaluation. Its
  pass threshold is 0.85 and a locally consistent but globally wrong attempt
  still scores 0.857 on seven of its ten pairwise vectors, so those vectors have
  no discriminating negative control. The exact-instance gate refuses them; the
  plan and report name the exclusion and the dropped case count.
* `representation` is pinned to `revealed` for `recursive_coarse_graining`,
  `recursive_compiler_bootstrap` and `recursive_error_correcting_codes`. The
  judge cannot replay its own reference certificate from an `inferred` instance,
  so those columns are unscored instead of guessed at. Pins are recorded per case
  (`study.pinned_levels`) and in the manifest (`study.axis_pins`).
* There is no compile-only path. A case whose judge cannot be behaviourally
  certified is dropped, never relabelled as validated.

## Known limits

* The reference patches embed the environment's own oracle (`network.py`). The
  gate proves that the *judge* separates a correct from an incorrect patch on the
  exact instance; it is not an independent second solver.
* The gate runs on the host (`sandbox="local"`); Docker isolation is proven by
  the live path, not by the gate.
* A `gates_only` run records no model results by construction, so its report is
  all `missing_result` — that is the correct output, not a failure of the report.
