# Free and trial provider profiles

**Epistemic status:** provider limits, model rosters, endpoint compatibility, and
free allowances change. This repository does not use a quota number as a
scoring assumption. Before a sweep, check the provider's current console and
run the provider preflight against the account that will actually be used.

## Credential resolution and safety

The host controller resolves credentials in this order:

1. `--api-key`;
2. `--api-key-env` and that environment variable;
3. the provider-specific environment variable;
4. `secret_key.json`, when present and gitignored/private;
5. fail without an interactive prompt.

Use `--secrets secret_key.json` to select an explicit profile. A local
`secret_key.json` must be ignored by Git, must not be tracked, and must have
private permissions such as `chmod 600`. The file is read by the host only.
The API key is never passed as a Docker argument, mounted into an agent/judge
container, written to a manifest, or included in provider-preflight output.

Create the local file from the committed template:

```bash
cp secret_key.example.json secret_key.json
chmod 600 secret_key.json
# edit the local file; do not paste it into a prompt or commit it
```

## Provider profiles

The named profiles below are OpenAI-compatible where the provider currently
supports that interface. Compatibility and access are account-specific; use
`custom` with an explicit `--api-base` if an endpoint needs a different adapter.

### Groq

- Console: <https://console.groq.com/keys>
- Example base: `https://api.groq.com/openai/v1`
- Environment variable: `GROQ_API_KEY`
- Check the current quickstart, model roster, and rate-limit pages before a
  batch. Prefer bounded context and output limits when token-per-minute limits
  are tight.

### NVIDIA hosted endpoints

- Console/catalog: <https://build.nvidia.com>
- Example base: `https://integrate.api.nvidia.com/v1`
- Environment variable: `NVIDIA_API_KEY`
- Model availability, trial access, and rate limits are account/model
  dependent. List models before selecting a pinned model.

### Gemini API / AI Studio

- Console: <https://aistudio.google.com/apikey>
- OpenAI-compatible example base:
  `https://generativelanguage.googleapis.com/v1beta/openai/`
- Environment variables: `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- Confirm the active project limits and data-use terms in AI Studio. Do not
  assume a fixed RPM/RPD allowance.

### OpenRouter

- Console: <https://openrouter.ai/keys>
- Base: `https://openrouter.ai/api/v1`
- Environment variable: `OPENROUTER_API_KEY`
- Free model IDs and account request limits rotate. Use a small declared
  budget; failed attempts may still consume an allowance.
- The client sends `HTTP-Referer` and `X-OpenRouter-Title` headers.

### Cloudflare Workers AI

- Account API and model catalog: <https://developers.cloudflare.com/workers-ai/>
- Endpoint paths are account-scoped and can change; put the exact base URL in
  the profile and verify it with preflight.
- Environment variable: `CF_API_TOKEN`; an account ID may be stored as profile
  metadata but must not be treated as a secret key.
- Treat the daily allowance as a small operational budget until the console
  confirms the current account terms.

### Atria, AgentRouter, WorkBuddy, and other trials

Verify the exact account, endpoint, authentication method, model IDs, free
allowance, expiry, and data-use terms from first-party documentation. If the
service is not OpenAI Chat Completions compatible, add a dedicated adapter
rather than silently sending it through `custom`.

## Preflight

Probe only providers that are enabled in the local profile:

```bash
python tools/provider_preflight.py \
  --secrets secret_key.json \
  --out runs/provider_preflight.json
```

The output contains only structured provider status, latency, status code,
error type, optional request ID, and model IDs (plus aggregate run metadata). It
does not contain endpoints, keys, or raw response bodies. A failed preflight
is a reason to stop or change the declared provider configuration, not a reason
to enable a paid fallback.

## Suite roles

These are planning suggestions, not measured model claims:

| workload | possible first candidates |
|---|---|
| short direct-answer cases | Groq, Gemini, a bounded free OpenRouter model |
| multi-turn coding episodes | NVIDIA, Gemini, or an account-approved trial |
| tiny cross-checks | OpenRouter free or Cloudflare, if the account permits it |

Record provider, model, endpoint, preflight result, budget, and data-use terms
with every run. Keep direct-answer, solver-synthesis, recurrent-depth, and ML
repair results in separate scoreboards.
