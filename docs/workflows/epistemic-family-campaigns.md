# Epistemic family model campaigns

Two manual GitHub Actions workflows evaluate all nine interactive epistemic
families using the providers from the recent campaigns:

| Workflow | Model | Repository secret |
|---|---|---|
| [Mercury](../../.github/workflows/epistemic-mercury-campaign.yml) | `mercury-3`, high reasoning effort, Chat Completions, temperature 1 | `INCEPTION_API_KEY` |
| [Reasoning Atria](../../.github/workflows/epistemic-reasoning-atria-campaign.yml) | `Atria-Dawn-Preview`, high reasoning effort, Responses | `ATRIA_API_KEY` |

The Atria profile uses `https://discovery-api.intern-ai.org.cn/v1`, matching
the reasoning Atria pairwise campaign. Mercury uses
`https://api.inceptionlabs.ai/v1`. Both use sequential requests, with minimum
intervals of 1,100 ms and 200 ms respectively. Other workflows using the same
account still share the provider's quota.

The Mercury profile follows Inception's [model documentation](https://docs.inceptionlabs.ai/get-started/models.md)
and [reasoning-effort documentation](https://docs.inceptionlabs.ai/capabilities/reasoning-efforts.md):
`mercury-3` accepts `max_completion_tokens` and `reasoning_effort: high`.
Requests explicitly use its default temperature of 1, within the supported
0.5–1 range.

The workflows share [one implementation](../../.github/workflows/epistemic-families-campaign.yml).
Their profiles live in
[epistemic_mercury_campaign.yaml](../../experiments/epistemic_mercury_campaign.yaml)
and [epistemic_reasoning_atria_campaign.yaml](../../experiments/epistemic_reasoning_atria_campaign.yaml).
The existing [configuration/replay workflow](../../.github/workflows/epistemic-families-validation.yml)
continues to run the regression checks on relevant changes.

## Launch from GitHub Actions

Commit the workflows, profiles, runner, provider adapter and accompanying family
code together. GitHub requires the manual workflow entry points on the default
branch before displaying their **Run workflow** buttons. Select the desired
revision in that button's branch selector.

1. Open **Epistemic families - Mercury campaign** or
   **Epistemic families - reasoning Atria campaign**.
2. Run `execution_mode: plan` to save the exact cases and resource bounds.
3. Run `reference` to exercise those cases and verify the recorded episodes.
4. Select `live` to run model evaluations with the corresponding repository secret.

Planning and reference execution do not use a provider key. Provider secrets are
available only to the live execution step. Each live instance runs a reference
control before model access. Requests contain fixed protocol instructions and
the current public JSON view. Private seeds, controller audits, reference
answers and earlier views are excluded from model context. In particular, the
memory family's retention boundary does not carry the exposure forward in a
chat history or a provider response ID.

| Input | Meaning |
|---|---|
| `family` | All nine families, or one selected family. |
| `matrix` | `configured` uses each family's YAML axes; `single` varies individual axes; `pairwise` covers pairs of axis levels and includes the uniform difficulty settings. |
| `attempts` | 1–10 separately recorded model attempts on each fixed instance. |
| `max_requests` | Campaign-wide HTTP request ceiling, initially 512; profile maximum 20,000. |
| `max_episodes` | Episode attempts in this invocation before checkpointing; initially 25. |
| `resume_run_id` | The completed run containing the latest checkpoint for this provider; empty starts a new campaign. |
| `resume_run_attempt` | The source run's attempt number; initially 1. |

The default pairwise plan can require more than the initial 512-request bound.
Use the plan to choose the live bound before starting. Mercury requests allow
at most 32,768 output tokens; Atria requests allow 8,192. Both have a 120-second
timeout, and each episode allows at most 32 turns.
The runner reserves capacity for all 32 turns before starting an episode, so it
can pause with fewer than 32 requests remaining. It similarly reserves enough
time for an entire episode before starting it.
The HTTP ceiling counts attempted requests, including unsuccessful requests.
It bounds generated tokens by request count times the per-request cap; input
tokens and monetary cost are separate. Recorded usage is whatever the provider
reports. Missing usage is not counted as zero measured consumption.

Token-limit cutoffs, refusals and invalid model output end the current episode
without producing a score; the campaign records the outcome and continues to
the next case. Transport failures, unsuccessful HTTP responses and malformed
provider responses halt the campaign. Raw response evidence is retained for
both kinds of outcome, and replay verifies the recorded classification.

The matrix describes coverage of configured axis levels. These public fixtures
and repeated attempts are not independent structural samples, and their level
names do not establish empirical difficulty. Reports retain each family's
metrics separately instead of inventing a cross-family score.

## Continue a saved campaign

Each invocation uploads its full state, plan, source hashes, request/response
records, reference controls, model episodes, replay results and report. The
Actions summary shows completed attempts and the reason execution stopped.
Artifact names include both run ID and run attempt:

```text
epistemic-mercury-state-RUN_ID-RUN_ATTEMPT
epistemic-atria-state-RUN_ID-RUN_ATTEMPT
```

Start a **new manual dispatch**, enter the latest state run ID and attempt, and
keep the same family, matrix, attempt count, execution mode and request ceiling.
The invocation's `max_episodes` can change. Resume restores the original source
revision and verifies the source, profile, plan and recorded evidence before
making another request. Completed attempts, including invalid model answers,
are retained. A reference campaign cannot be promoted into a live campaign;
start a separate live run after reviewing its controls.

Only the newest state artifact for a provider can be resumed. This prevents
accidentally branching an old checkpoint and billing the same cases again.
Plan artifacts have a separate prefix and do not supersede running campaigns.
One invocation per provider can run at a time. Use a new manual resume instead
of GitHub's **Re-run jobs** button for live campaigns.

An invocation limit is a resumable pause. The campaign request ceiling remains
fixed after the first execution. Unknown interrupted requests, missing evidence,
source changes and incompatible plans stop before further provider access.
There are no automatic HTTP retries or scheduled continuations. The retained
evidence is the record to inspect after an interruption; an ambiguous paid
request is never silently repeated. Artifacts are retained for 90 days.

## Local execution

From the repository root with Node.js 24 and locked dependencies installed:

```sh
npm ci
npm test
node tools/epistemic_family_campaign.mjs plan --profile experiments/epistemic_mercury_campaign.yaml --output mercury-plan --family all --matrix pairwise --attempts 1 --max-requests 512
node tools/epistemic_family_campaign.mjs run --profile experiments/epistemic_mercury_campaign.yaml --output mercury-reference --execution-mode reference --family all --matrix configured --attempts 1 --max-requests 512 --max-episodes 25
node tools/epistemic_family_campaign.mjs verify --profile experiments/epistemic_mercury_campaign.yaml --output mercury-reference
```

For live execution, supply the profile's API key through the environment and use
`--execution-mode live` with a new output directory. Reuse that directory and
the same plan options to continue a checkpoint. Local execution has the same
ledger and compatibility checks; GitHub's artifact freshness and concurrency
checks apply only in Actions.
