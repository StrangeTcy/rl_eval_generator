# Recursive gluing frontier evaluation (manual dispatch)

This directory holds the copyable workflow source. GitHub executes only
`.github/workflows/recursive-gluing-eval.yml`; it does not execute the docs copy.
The reviewed source is staged at `docs/workflows/recursive-gluing-eval.yml.example`.

| File | Role |
| --- | --- |
| `docs/workflows/recursive-gluing-eval.yml.example` | Copyable workflow: manual dispatch only, no schedule, one provider/model pair per dispatch. |
| `tools/recursive_gluing_study.py` | `plan` / `run` / `report` for the study. Builds a filtered manifest and provider-free budget plan, forwards live execution to `tools/run_suite.py`, and turns the checkpoint into JSON + CSV + Markdown. |
| `tools/recursive_references.py` | Host-side correct/wrong patch pairs for the exact-instance gate. Never part of the agent-facing tree. |
| `docs/decisions/2026-10-16-sheaf-recursive-reasoning.md` | Why the family exists and what the diagnostic matrix is testing. |

## What one dispatch does

1. **Plan (provider-free).** Builds the manifest for the requested
   `scope`/`matrix`/`seeds`/shard and checks every ceiling before anything is
   generated or called. A plan that does not fit exits non-zero. The plan is
   uploaded as an artifact and written to the job summary.
2. **Gate (provider-free).** Generates each requested case once and grades
   three patches against its real judge: an empty no-op must score 0, a
   plausible-but-wrong patch must fail the named held-out check, and the
   reference must pass. Any case that does not discriminate is reported in
   `instance_oracles.json` and stops the run. No provider call is made in this
   step.
3. **Live (`execution_mode=live` only).** Re-checks the gate from the
   checkpoint, then runs with the operator's ceilings. A quota/auth failure
   pauses the run instead of retrying; ceilings are never raised automatically.
   An unrecorded case is not counted as a scored zero or `unsat`.
4. **Report (always).** Produces JSON, CSV and Markdown per environment and
   factor, with every case's outcome class, hidden-check breakdown, usage and
   latency.

## Budget arithmetic

| Dispatch | Cases | Worst-case API calls | Worst-case output tokens | Wall estimate |
| --- | --- | --- | --- | --- |
| `scope=diagnostic` (`max_steps=24`, `max_tokens=4096`) | 18 | 1296 | 5,308,416 | 14,400 s |
| `scope=family matrix=pairwise` (all certified members) | 76 | 5,472 | 22,413,312 | 49,200 s; needs 4 shards |

The wall estimate is a ceiling, not a forecast: `cases × 600 s + 3600 s` of
gate reserve. A GitHub job may run at most six hours, so the pairwise family
run is split into four disjoint shards of 19 cases / 15,000 s each.

## Deployment status

The workflow source is in `docs/workflows/recursive-gluing-eval.yml.example`.
The active copy is `.github/workflows/recursive-gluing-eval.yml`; both are kept
in sync on this study branch. Select the study branch in the GitHub Actions UI
when dispatching. If updating the workflow in GitHub's web editor, copy the
reviewed docs source into the active workflow path before committing.

## AgentRouter provider, endpoint, key and model

`agentrouter` is an explicit provider choice and the intended study provider.
It retains its existing OpenAI-compatible Chat Completions default at
`https://agentrouter.org/v1`. The workflow's optional `api_base` input can
explicitly override that endpoint when a study dispatch requires another
AgentRouter-compatible base.

For a live run, add the API key in the repository's **Settings → Secrets and
variables → Actions** as `AGENTROUTER_API_KEY`. The workflow maps that exact
secret name into the live step. It also accepts `AGENT_ROUTER_API_KEY` and
`AGENTROUTER_API_TOKEN` as aliases. GitHub never shows a saved secret value
again; it only lets an owner replace it. Do not put the key in a model input,
log, issue, or chat.

The official [AgentRouter model catalog](https://co.agentrouter.org/portal/models)
currently lists GPT-5.5, and the official [OpenAI-compatible integration guide](https://co.agentrouter.org/portal/guide)
identifies its model ID as `gpt-5.5`. The same current catalog does not list
`gpt-6-astra`; that ID should not be used for this endpoint unless AgentRouter
adds it to the account's catalog. The endpoint's `/v1/models` route requires an
API key, so an account-specific roster cannot be checked without that
credential. The evaluator does not resolve aliases or query the catalogue.
`plan_only` needs no key and makes no provider calls. Other providers remain
selectable; use them only when they are the intended experiment condition.

### Diagnosing an authentication failure

The live workflow maps the exact secret names above. If the secret name is
missing or misspelled, the controller fails before an HTTP request. A response
from the endpoint with HTTP 401 `Invalid API Key!` means a credential reached
the endpoint and was rejected; that is different from a missing-secret failure.
The run record's `api_key_env=SUITE_API_KEY` is the controller's generic
credential-variable label, not the GitHub secret name. If the repository has
`AGENTROUTER_API_KEY` and the run returned HTTP 401, you have already completed
the GitHub name/mapping check; do not create a `SUITE_API_KEY` secret just
because that label appears in the report. The secret value cannot be inspected
from GitHub after saving. Check in AgentRouter that the key is an active API key
for this account (not a dashboard login token); if you cannot confirm the
copied value, replace the repository secret with the key again. Do not rerun a
live campaign until the key is checked or replaced.

## YepAPI and Synapse Garden

The manual workflow offers these first-class OpenAI-compatible providers:

| Provider | Credential secret | Default base URL | Chat Completions model |
| --- | --- | --- | --- |
| `yepapi` | `YEPAPI_KEY` | `https://api.yepapi.com/v1/ai` | `openai/gpt-6-astra` |
| `synapse_garden` | `SYNAPSE_API_KEY` | `https://synapse.garden/api/v1` | `openai/gpt-6.1-sol` |

Both use the provider-neutral `/chat/completions` client and keep
`wire_api=chat_completions`. YepAPI uses `x-api-key`; Synapse Garden uses
`Authorization: Bearer`. The YepAPI implementation calls
`/v1/ai/chat/completions` (the OpenAI-compatible snake_case API), not the
separate `/v1/ai/chat` simplified API. Synapse Garden calls
`/api/v1/chat/completions`. Provider preflight shares the same centralized
header policy. Keys are passed only in the live step and stripped from the
agent/judge process environment; no live request is made by tests.

Reference docs: [YepAPI Chat Completions](https://docs.yepapi.com/ai-models/chat-completions),
[GPT-6 Astra](https://docs.yepapi.com/ai-models/openai/gpt-6-astra),
[YepAPI authentication](https://docs.yepapi.com/getting-started/authentication),
[Synapse Garden authentication](https://synapse.garden/docs/authentication),
[API reference](https://synapse.garden/docs/api-reference), and
[GPT-6.1 Sol](https://synapse.garden/models/openai/gpt-6.1-sol).

## Dispatching in the GitHub Actions UI

1. Open **Actions → Recursive gluing frontier evaluation → Run workflow** and
   select the study branch.
2. For a free preflight, set `execution_mode=plan_only`, `scope=diagnostic`,
   `provider=agentrouter`, `model=gpt-5.5`, `wire_api=chat_completions`, and leave
   `api_base` blank (the documented `co.agentrouter.org` URL is now the default).
   Review the plan and budget in the job summary/artifact. This mode makes no
   model call.
3. For a bounded first-class-provider pilot, keep `scope=diagnostic`, set
   `seeds=0`, `shard_count=8`, `shard_index=0`, `max_steps=1`,
   `max_tokens=256`, `max_api_calls=6`, `max_tokens_total=1536`, and
   `max_wall_seconds=4800`. These select the two-case shard. Even on workflow
   revisions without a `max_http_attempts` input, the study controller applies
   a six-request HTTP-attempt backstop for YepAPI and Synapse Garden, including
   retries. Inspect responses and provider usage before expanding.
4. The full diagnostic run is 18 cases. Review the plan's maximum calls and
   tokens and deliberately raise ceilings before authorizing a broader run. For
   a family pairwise rerun, use separate live dispatches with `scope=family`,
   `matrix=pairwise`, and explicit shard and budget values.
5. Open the run's **Summary** for identity, plan and outcome. Download the
   `recursive-gluing-results-...` artifact for the checkpoint and reports
   (`report/results.json`, `report/results.csv`, and `report/summary.md`).

Each shard is a separate artifact; duplicate grading is reported, not silently
averaged.

## Coverage the study refuses

* `recursive_holonomy_gluing` is excluded from live scored evaluation. Its pass
  threshold is 0.85 and a locally consistent but globally wrong attempt still
  scores 0.857 on seven of its ten pairwise vectors, so those vectors have no
  discriminating negative control. The exact-instance gate refuses them; the
  plan and report name the exclusion and dropped case count.
* `representation` is pinned to `revealed` for `recursive_coarse_graining`,
  `recursive_compiler_bootstrap` and `recursive_error_correcting_codes`. The
  judge cannot replay its own reference certificate from an `inferred`
  instance, so those columns are unscored rather than guessed at. Pins are
  recorded per case (`study.pinned_levels`) and in the manifest
  (`study.axis_pins`).
* There is no compile-only path. A case whose judge cannot be behaviourally
  certified is dropped, never relabelled as validated.

## Known limits

* The reference patches embed the environment's own oracle (`network.py`). The
  gate proves that the judge separates a correct from an incorrect patch on the
  exact instance; it is not an independent second solver.
* The gate runs on the host (`sandbox="local"`); Docker isolation is proven by
  the live path, not by the gate.
* A `gates_only` run records no model results by construction, so its report is
  all `missing_result` — that is the correct output, not a report failure.
