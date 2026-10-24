# Reasoning Atria / Mercury on the recursive-gluing study — bounded pilot attempt

Date: 2026-10-23
Branch: `arena/192dc25c-rl-eval-generator` (base `9c3ce418`)
Code commit: `eba18e2` (`providers: enforce the physical HTTP-attempt budget on the Responses wire`)

**Outcome in one line: no scored live episode was produced, because this environment has
neither the provider credentials nor a network route to either provider, and the GitHub
Actions dispatch that does hold them is refused to the integration token (HTTP 403).**
Everything that can be established provider-free was run and is recorded below: the plan,
the exact-instance gate, the credential/endpoint probe, a controller-command audit, and an
offline end-to-end run of the real controller + judge with a stubbed transport. The blocker
is the *first* failing layer — a missing credential — not a code defect.

---

## 1. What the checkout already had (no capability had to be invented)

`atria` and `mercury` are first-class providers here; `wire_api` and `reasoning_effort`
are threaded from the study CLI through the manifest, the controller command and the
request body. Verified, not duplicated:

| Layer | File | State |
|---|---|---|
| Credential resolution | `arena/secrets.py` | `atria` → `ATRIA_API_KEY`, base `https://api.atria-asi.ai/v1`; `mercury` → `INCEPTION_API_KEY` (alias `MERCURY_API_KEY`), base `https://api.inceptionlabs.ai/v1` |
| Request shaping | `arena/providers.py` | `complete_responses()` sends nested `reasoning: {effort}` + `max_output_tokens`; `complete()` sends Mercury's flat `reasoning_effort` + `max_completion_tokens` |
| Wire selection | `arena/episode.py::_complete_with_wire_api` | refuses Atria reasoning on Chat Completions and refuses a non-Mercury flat reasoning field |
| Study CLI | `tools/recursive_gluing_study.py` | `--wire-api`, `--reasoning-effort`, `--max-http-attempts`, `--invalid-retries`; reasoning is only accepted for `(mercury, chat_completions)` and `(atria, responses)` |
| Controller | `tools/run_suite.py` | forwards `wire_api` / `reasoning_effort` verbatim into `arena.py run` |
| Workflow | `.github/workflows/recursive-gluing-eval.yml` | exposes `wire_api` / `reasoning_effort`, exports `ATRIA_API_KEY` / `INCEPTION_API_KEY` only on the live step |

**Live history found:** every prior `Recursive gluing frontier evaluation` dispatch used
`synapse_garden` (runs 39572666271, 39580706886, 39586680263) or `yepapi` (39559222329,
39555638004), and all ended with exit 3 (controller paused). No Atria or Mercury
recursive-gluing dispatch has ever been attempted, so there was no "existing failure" to
reproduce for either target provider.

### The one real code defect found and fixed

`ProviderClient.complete_responses` — the only path Atria controlled reasoning can use —
did not participate in the client's *physical HTTP-attempt* accounting:

* it never reset `last_attempts` / `last_attempt_logs` / `last_retry_count` / `last_http_attempts`;
* it never incremented `http_attempts_used` and never refused a request once
  `--max-http-attempts` was spent;
* successful calls and retried failures were not written to the attempt log that the
  controller's trace and `api_errors.jsonl` are built from.

A dispatch could therefore declare a 192-attempt ceiling and get a trace reporting
`attempt_count: 0`, no record of retried attempts, and no enforcement of the budget the
provider-free plan had authorised. Fixed in `arena/providers.py` (accounting only — URL,
body, retry policy and parsing unchanged) with four offline regression tests in
`tests/test_provider_request_shaping.py`:

* `test_responses_counts_physical_attempts_and_records_them`
* `test_responses_retries_are_logged_and_counted`
* `test_responses_stops_retrying_when_the_physical_budget_is_spent`
* `test_responses_refuses_a_request_once_the_budget_is_already_spent`

---

## 2. Provider-free validation (run, passed)

### 2.1 Deterministic two-case slice

`--seeds 1` selects the curated held-out stability cell, which is exactly one case per
primary environment. Both providers were planned against the **same** case IDs.

```
recursive_gluing__recursive_depth=hard_state_space=hard_gluing_regime=hard_label_opacity=hard__seed-1
recursive_gluing_discovery__recursive_depth=hard_state_space=hard_gluing_regime=hard_label_opacity=hard_structural_ambiguity=hard__seed-1
```

Manifest hashes of the recorded plan artifacts (the manifest embeds `created_at` and a
`dirty` flag, so regenerate rather than trusting a copied byte hash):

* `runs/pilot_plan_atria/study_manifest.json` — `ad7cec6c64db0cdcfffe53801a93664706575333be9382aa677744189ef4dc8d`
* `runs/pilot_plan_mercury/study_manifest.json` — `a1e7e34e386dedfb9b1834a927c618e45cac33a85e3fd9b5e9f7222c6955d1e7`

Plan arithmetic (identical for both providers, sealed by `plan.json`):

| Quantity | Value | Ceiling checked |
|---|---|---|
| cases | 2 (one per primary environment) | — |
| per-episode steps / output tokens | 8 / 1024 | — |
| invalid-response retries | 2 | — |
| logical API calls | 24/case → 48 | 48 ✔ |
| output tokens | 24 576/case → 49 152 | 49 152 ✔ |
| physical HTTP attempts | 48 × (1 + 3 controller retries) = 192 | 192 ✔ (derived) |
| wall clock | estimate 4 800 s, minimum 240 s | 4 800 s ✔ |

`within_limits: true`, `warnings: []` for both.

### 2.2 Exact-instance oracle gate

`tools/instance_oracle_gate.py --manifest …` on the frozen slice, provider-free
(`provider_calls: 0`, `instance_coverage_complete: true`):

| environment | no-op | plausible wrong | reference |
|---|---|---|---|
| `recursive_gluing` | FAIL 0.0 | FAIL 0.167 | **PASS 1.0** |
| `recursive_gluing_discovery` | FAIL 0.0 | FAIL 0.104 | **PASS 1.0** |

Artifacts: `runs/pilot_gate_atria.json`, `runs/pilot_gate_mercury.json`.
Both manifests carry byte-identical cases, so the gate result is shared evidence, not two
independent claims.

### 2.3 Credential / endpoint probe (sanitized)

`tools/provider_preflight.py --provider atria --provider mercury` →
`runs/pilot_preflight.json`: both `credential_error`, `reachable_count: 0`, no key value
printed. The first failing layer, named exactly (`runs/pilot_blocker.json`):

```
atria   ValueError: No API key for provider 'atria'; set ATRIA_API_KEY or add
        providers.atria.api_key to secret_key.json
mercury ValueError: No API key for provider 'mercury'; set INCEPTION_API_KEY or add
        providers.mercury.api_key to secret_key.json
```

This is *not* an authentication rejection (401), a quota failure, or a model-ID problem —
no request was ever constructed. Secondary probes, recorded so the next attempt is not
ambiguous:

* direct HTTPS to `https://api.atria-asi.ai/v1/models` and
  `https://api.inceptionlabs.ai/v1/models` → `URLError: TLS/SSL connection has been closed (EOF)`.
  This sandbox has no egress to either provider, so even with a key supplied it could not
  have made a model call.
* `POST /repos/.../actions/workflows/390580639/dispatches` → `HTTP 403: Resource not
  accessible by integration`; `GET /repos/.../actions/secrets` → same 403. The one host
  that *does* hold the Actions secrets and *does* have provider egress cannot be driven
  from here. No `--auto`/retry workaround exists, and inventing one was out of scope.

### 2.4 Controller-command audit

`run_study` was invoked with a stub runner to capture exactly what it forwards:

```
atria   : provider=atria   model=Atria-Dawn-Preview api_key_env=ATRIA_API_KEY
          wire_api=responses reasoning_effort=high api_base=<unset → https://api.atria-asi.ai/v1>
          max_steps=8 max_tokens=1024 invalid_retries=2 max_retries=3 max_http_attempts=192
mercury : provider=mercury model=mercury-2.5        api_key_env=INCEPTION_API_KEY
          wire_api=chat_completions reasoning_effort=high api_base=<unset → https://api.inceptionlabs.ai/v1>
          max_steps=8 max_tokens=1024 invalid_retries=2 max_retries=3 max_http_attempts=192
```

Resolved endpoints: `https://api.atria-asi.ai/v1/responses` and
`https://api.inceptionlabs.ai/v1/chat/completions`. Per-case argv from
`run_suite._build_command` carries `--wire-api` and `--reasoning-effort` verbatim, and the
key is only ever passed as `--api-key-env <NAME>`, never as a value.

---

## 3. Offline end-to-end wiring check — **not a model result**

Because the transport could not reach either provider, the controller was exercised with a
stubbed transport (`runs/pilot_offline_wiring/verify_wiring.py`) that *receives the exact
body the real client would send*, asserts its shape, and answers with the environment's own
host-side oracle reference as a `write_file` action, then `submit`. This proves the
request → parse → action → submit → **independent judge** path; it proves nothing about any
model's capability, and these rows must never be aggregated into a score.

| provider / wire | case | body the transport actually saw | result |
|---|---|---|---|
| atria / `responses` | `recursive_gluing` seed 1 | `{"model":"Atria-Dawn-Preview","reasoning":{"effort":"high"},"max_output_tokens":1024,"input":[…messages…]}`, no `messages`/`max_tokens` keys | judge **PASS 1.0**, 18/18 checks, `failure_mode: pass` |
| atria / `responses` | `recursive_gluing_discovery` seed 1 | same shape | judge **PASS 1.0**, `assembled_unsat` / `opaque_twin` / `decoy_heldout` … all true |
| mercury / `chat_completions` | `recursive_gluing` seed 1 | `{"model":"mercury-2.5","max_completion_tokens":1024,"request_extra":{"reasoning_effort":"high"},"temperature":0.0}` | judge **PASS 1.0**, `failure_mode: pass` |

So: the Atria nested reasoning field and the Mercury flat reasoning field both reach the
wire unchanged, and a response on either wire does reach the independent judge. What is
missing is only a real model response.

---

## 4. Classification of what was and was not obtained

| Category | Status |
|---|---|
| validated success | **none** (no model call was possible) |
| scored model failure | none |
| incorrect satisfiability decision | none |
| malformed / incomplete output | none |
| provider failure | none (no request left the host) |
| infrastructure failure | **yes, blocking**: missing credential + no provider egress + Actions dispatch refused (403) |
| oracle / gate failure | none — gate passed on both cases |
| timeout / resource exhaustion | none |
| missing result | **the pilot's two cases, for both providers** |

Not attempted, deliberately: the 18-case diagnostic campaign, the family matrix, raising any
ceiling, or falling back to Astra/Fable/AgentRouter/YepAPI/Synapse Garden.

---

## 5. Reproduce

### 5.0 Dispatchable pilot (for a run I cannot start from here)

This sandbox's GitHub token is a GitHub App installation token with **no OAuth
scopes** (`X-OAuth-Scopes:` empty), and both `POST …/actions/workflows/<id>/dispatches`
and `GET …/actions/secrets` answer `403 Resource not accessible by integration`,
retried and reconfirmed on 2026-10-23. It also cannot write `.github/workflows/**`.
So the live leg has to be your manual dispatch, which matches how workflows are
deployed here (reviewed copy in `docs/`, hand-copied to `.github/workflows/`).

Prepared for exactly that: **`docs/workflows/recursive-gluing-reasoning-pilot.yml.example`**
(a `workflow_dispatch`-only pilot wrapper, test-locked by
`test_reasoning_pilot_workflow_pins_the_frozen_slice_and_its_ceilings`).

What it pins, so no dispatch can drift from this report:

| Element | Value | Why |
|---|---|---|
| inputs | only `provider` (`atria`/`mercury`) and `execution_mode` (`plan_only`/`live`) | a ceiling or a case count is not dispatchable, so the pilot cannot become a campaign |
| model / wire / effort | derived from `provider` (`Atria-Dawn-Preview`+`responses`+`high`; `mercury-2.5`+`chat_completions`+`high`) | the mismatched pairs are unrepresentable, and the study refuses them provider-free anyway |
| slice | `scope=diagnostic`, `seeds=1` → the same two case ids | comparable across providers |
| ceilings | 48 calls, 49 152 tokens, 4 800 s, 8 steps, 1 024 tokens/response, 2 invalid retries, 192 physical attempts (derived) | identical to §2 |
| credential | `ATRIA_API_KEY` / `INCEPTION_API_KEY` (alias `MERCURY_API_KEY`) exposed only on the live step; the step refuses before the first call if the selected one is absent | a missing secret is a dispatch problem, exit 2, never a model result |

To run it: copy the file to `.github/workflows/recursive-gluing-reasoning-pilot.yml`
on this branch, commit, then dispatch `provider=atria, execution_mode=plan_only`
(provider-free), then `execution_mode=live`; repeat for `mercury`. The job summary
prints identity → plan → gate → per-case outcome or a named pause. Full click-path
in `docs/workflows/recursive-gluing-eval.md` → *Reasoning pilot (Atria / Mercury)*.

### 5.0.1 Post-mortem: the first pilot dispatch (run 40067626107) failed in my workflow

`main@758a201` — the hand-copied copy of §5.0 — failed in **Plan** after ~1 s, with
Gates/Live skipped, `runs/recursive_gluing_pilot_plan` missing from the artifact
upload, and the job exiting 1. **No provider call was made and nothing was
spent.** (Provider: `atria`, `execution_mode=plan_only`.)

Cause, reproduced locally by executing the resolver and plan steps in sequence:

```
/tmp/plan_step.sh: line 17: MODEL: unbound variable
```

The resolver exported `model=`/`wire_api=`/`reasoning_effort=`/`key_env=`/`api_base=`
into `$GITHUB_ENV`, while the Plan, Gates and Live steps dereference
`$MODEL`/`$WIRE_API`/`$REASONING_EFFORT`/`$KEY_ENV`/`$API_BASE`. Under `set -u`
the first unset read aborted the step, so no plan was written and every later
step was skipped. My earlier checks did not catch it: the YAML parsed, `bash -n`
passed for each step, and each script was self-consistent in isolation — only
running the *pair* in order exposes it.

Fixed in `docs/workflows/recursive-gluing-reasoning-pilot.yml.example` (uppercase
exports, with a comment naming this run), and locked by a new test that executes
the resolver, asserts every variable the later steps read is what the resolver
exported, then runs the plan step under `set -u` and checks the resulting
`plan.json`. Against the failed workflow that test reports exactly:

```
AssertionError: Plan (provider-free) reads $MODEL but the resolver exported
['api_base', 'key_env', 'model', 'reasoning_effort', 'wire_api']
```

Re-verified locally, provider-free, after the fix: resolver → **Plan** (2 cases,
`within_limits: true`, 192 derived attempts) → **Gates**
(`provider_free_validation_complete: true`, both cases certified) → **Report**
(2 rows, both `missing_result`, which is the correct reading for a gates-only
leg) → **Diagnose** (`complete`, 0 of 2 recorded). The live step's command line
was audited with a stubbed `python`:

```
run --manifest …/study_manifest.json --out … --execution-mode live --provider atria
    --model Atria-Dawn-Preview --wire-api responses --reasoning-effort high
    --api-key-env ATRIA_API_KEY --max-api-calls 48 --max-tokens-total 49152
    --max-wall-seconds 4800 --max-steps 8 --max-tokens 1024 --invalid-retries 2
    --gate-context-sha <sha>
```

### 5.0.2 Run result: 40068694722 (`main@71f1289`, atria, live) — credential rejected

First run that reached the provider. Plan ✓, Gates ✓ (both cases certified), Live ✗
with exit 3 = the controller's *paused* code. Read from the check-run annotations
(the artifact zip and job logs are on `blob.core.windows.net`, which this sandbox
cannot reach):

```
title: Recursive gluing credential_rejected (provider_error)
the provider rejected the credential: the endpoint rejected the credential;
a retry cannot fix it - replace the repository secret
case recursive_gluing__recursive_depth=hard_state_space=hard_gluing_regime=hard_label_opacity=hard__seed-1
  status=paused_provider_error elapsed=82.514s http_attempts=0
body: {"error":{"message":"Invalid API key.","type":"atria_api_error","code":"invalid_api_key"}}
next step: Replace the provider secret, then re-dispatch the same case list; do not retry the same key.
```

Reading:

* The credential **is configured** — the workflow's presence guard passed and a
  request reached Atria, which answered with its own `atria_api_error` body. So
  this is a *rejected* key (401-equivalent), not a missing secret (which would
  exit 2 before any call) and not a quota, rate-limit, model-ID, endpoint or
  protocol problem.
* Request shaping was therefore exercised end to end: the Responses call was
  built and transmitted. What failed is only its authorization.
* `http_attempts=0` is the *old* accounting: `main@71f1289` is `9c3ce41` + the
  workflow file, i.e. it predates this branch's `complete_responses` fix. The
  request did happen (Atria answered it); only the counter was not updated.
* `max_http_attempts: 96` in the episode manifest is correct and not a reduced
  ceiling: `run_suite` leases `min(global_remaining, per_case_calls × (retries+1))`
  = `min(192, 24 × 4)` = 96 to each case subprocess. The dispatch-wide budget the
  plan printed (192) was never at risk: 1 attempt was used.
* 1 of 2 cases has a disposition (`paused_provider_error`); the second was never
  attempted because the controller pauses the leg on a provider failure.

**Classification: provider/credential failure. Not a model result, not a scored
zero, not an UNSAT decision.** Per the pilot contract no retry of the same key was
attempted, no ceiling was raised, and no fallback provider was substituted.

Outstanding non-blocking note: `main` does not carry this branch's
`arena/providers.py` accounting fix, so attempt counts on `main` runs read 0.
Merging the branch (or dispatching from it) fixes the reporting, not the auth.

### 5.0.3 The Atria credential is now rejected - and it demonstrably worked last week

No key handling was needed to establish this; the repository's own campaign state
is the evidence. The same secret name (`ATRIA_API_KEY`) is mapped in every Atria
workflow (`.github/workflows/reasoning-atria-*.yml`, `atria-campaign.yml`,
`atria-first5.yml`), so the pilot is not using a different or misnamed secret.

| Campaign status issue | Recorded state | When |
|---|---|---|
| #20 Reasoning-Atria pairwise | **415 / 416 episodes checkpointed**, paused only on `max_tokens_total`; gate 189/189; 1 provider-outage retry | 2026-10-17T15:54Z |
| #21 Mercury pairwise | **416 / 416 episodes**, campaign `completed`; infrastructure retries only, no auth failures | 2026-10-16T11:27Z |

So on 2026-10-17 Atria-Dawn-Preview over `/v1/responses` with nested
`reasoning:{effort}` accepted this repository's credential and produced scored
episodes at scale. On 2026-10-24 the same secret returns Atria's own
`{"code":"invalid_api_key"}` (run 40068694722). The harness, endpoint, protocol,
model id and secret mapping are therefore unchanged and provably working; the
**credential's validity is what changed** between those dates (rotation,
revocation, expiry, or a dashboard token pasted instead of an API key). Only the
repository owner can act on that.

Consequence for this pilot, per its own contract: do not retry the same key, do
not raise a ceiling, do not substitute another provider to manufacture a result.
The remaining path to a scored episode is the other approved provider.

### 5.1 Provider-free validation on any host

Provider-free (works anywhere with Python + PyYAML + torch):

```bash
pip install -r requirements.txt && pip install torch==2.5.1 numpy   # judge imports torch

python tools/recursive_gluing_study.py plan --scope diagnostic --seeds 1 \
  --provider atria --model Atria-Dawn-Preview --wire-api responses --reasoning-effort high \
  --max-api-calls 48 --max-tokens-total 49152 --max-wall-seconds 4800 \
  --max-steps 8 --max-tokens 1024 --out runs/pilot_plan_atria

python tools/recursive_gluing_study.py plan --scope diagnostic --seeds 1 \
  --provider mercury --model mercury-2.5 --wire-api chat_completions --reasoning-effort high \
  --max-api-calls 48 --max-tokens-total 49152 --max-wall-seconds 4800 \
  --max-steps 8 --max-tokens 1024 --out runs/pilot_plan_mercury

python tools/instance_oracle_gate.py --manifest runs/pilot_plan_atria/study_manifest.json --out runs/pilot_gate_atria.json
python tools/instance_oracle_gate.py --manifest runs/pilot_plan_mercury/study_manifest.json --out runs/pilot_gate_mercury.json
python tools/provider_preflight.py --provider atria --provider mercury --out runs/pilot_preflight.json

python runs/pilot_offline_wiring/verify_wiring.py --provider atria   --environment recursive_gluing
python runs/pilot_offline_wiring/verify_wiring.py --provider mercury --environment recursive_gluing
```

### 5.2 Bounded live pilot

To be run **where `ATRIA_API_KEY` / `INCEPTION_API_KEY` exist and the provider is reachable**
(GitHub Actions dispatch, one provider per dispatch, or a host with egress). Nothing below
raises a ceiling. The workflow form (§5.0) is preferred because its ceilings cannot be
mistyped; the raw dispatch form is:

```bash
gh workflow run "Recursive gluing frontier evaluation" --ref <ref-with-this-commit> \
  -f scope=diagnostic -f execution_mode=live -f provider=atria -f model=Atria-Dawn-Preview \
  -f seeds=1 -f max_api_calls=48 -f max_tokens_total=49152 -f max_wall_seconds=4800 \
  -f max_steps=8 -f max_tokens=1024 -f wire_api=responses -f reasoning_effort=high

gh workflow run "Recursive gluing frontier evaluation" --ref <ref-with-this-commit> \
  -f scope=diagnostic -f execution_mode=live -f provider=mercury -f model=mercury-2.5 \
  -f seeds=1 -f max_api_calls=48 -f max_tokens_total=49152 -f max_wall_seconds=4800 \
  -f max_steps=8 -f max_tokens=1024 -f wire_api=chat_completions -f reasoning_effort=high
```

Local equivalent:

```bash
python tools/recursive_gluing_study.py run --manifest runs/pilot_plan_atria/study_manifest.json \
  --out runs/pilot_live_atria --execution-mode live --provider atria \
  --model Atria-Dawn-Preview --wire-api responses --reasoning-effort high \
  --max-api-calls 48 --max-tokens-total 49152 --max-wall-seconds 4800 --max-steps 8 --max-tokens 1024
```

Read the outcome with `python tools/recursive_gluing_study.py diagnose --run-out runs/pilot_live_atria`
(exit 2 = refused before any call, exit 3 = paused; 0 = every case has a disposition).

---

## 6. Test status

Focused (all pass, 99 + 4 new):

```
python -m pytest -q tests/test_provider_request_shaping.py tests/test_provider_reasoning_campaigns.py \
  tests/test_first_class_providers.py tests/test_recursive_gluing_study.py tests/test_atria_campaign.py \
  tests/test_agentrouter_provider.py tests/test_result_records.py tests/test_paid_campaign_safety.py \
  tests/test_launcher_flag_compatibility.py
```

Full suite: 8 failures, **all pre-existing at base commit `9c3ce41`** (verified by stashing
this branch's changes and re-running them): `test_inherit_campaign_state.py::test_plan_comes_from_the_same_builder_the_campaign_uses`
(stale `496` case count vs 582), `tests/test_pairwise_matrix.py` (5 profile/ceiling rows),
`tests/test_shortcut_gate.py::test_the_behavioral_tier_reports_a_skip_instead_of_a_pass`,
`tests/test_observational_equivalence_check.py::test_a_taxonomy_entry_alone_cannot_replan_a_campaign`.
None touch providers, the study runner, or the recursive-gluing references.

`git diff --check` clean.

---

## 7. Changed files

```
arena/providers.py                        # physical-attempt accounting on the Responses wire
tests/test_provider_request_shaping.py    # 4 offline regression tests
runs/pilot_plan_atria/                    # provider-free plan (plan.json, plan.md, study_manifest.json)
runs/pilot_plan_mercury/                  # provider-free plan
runs/pilot_gate_atria.json                # exact-instance gate, 2 cases
runs/pilot_gate_mercury.json              # exact-instance gate, 2 cases
runs/pilot_preflight.json                 # credential probe (sanitized)
runs/pilot_blocker.json                   # exact first-failing-layer evidence
runs/pilot_offline_wiring/                # transport-stub controller→judge wiring check (+ run dirs)
docs/workflows/recursive-gluing-reasoning-pilot.yml.example   # dispatchable pilot, frozen slice
docs/workflows/recursive-gluing-eval.md   # how to copy and dispatch it
tests/test_recursive_gluing_study.py      # locks the pilot workflow's contract
PILOT_EVIDENCE.md                         # this report
```

No generator, prompt, reference, hidden check or frozen experiment was modified.
