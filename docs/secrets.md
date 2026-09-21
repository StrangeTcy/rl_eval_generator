# Secrets

## Local profile

`secret_key.json` is a local, gitignored file. It must not be tracked and must
be private (`chmod 600`). The committed `secret_key.example.json` contains only
placeholders:

```json
{
  "providers": {
    "groq": {
      "api_key": "...",
      "api_base": "https://api.groq.com/openai/v1",
      "enabled": true
    }
  },
  "default_provider": "groq",
  "default_models": {
    "groq": "openai/gpt-oss-120b"
  }
}
```

Create it with:

```bash
cp secret_key.example.json secret_key.json
chmod 600 secret_key.json
```

The loader refuses a tracked profile, a profile that is not gitignored, or a
profile readable by group/other users. It does not prompt interactively.

## Environment variables

Environment variables take precedence over the profile file:

- `GROQ_API_KEY`
- `NVIDIA_API_KEY`
- `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- `OPENROUTER_API_KEY`
- `CF_API_TOKEN`
- `ATRIA_API_KEY`
- `API_KEY` for `custom`
- `HF_TOKEN` for Hugging Face

An explicit `--api-key-env` overrides the provider-specific variable. A literal
`--api-key` is supported for compatibility, but environment variables or the
local file are safer because command-line arguments can appear in shell history
and process listings.

## CLI examples

Use the profile explicitly:

```bash
python arena.py run \
  --provider groq \
  --model openai/gpt-oss-120b \
  --secrets secret_key.json \
  --env glyph \
  --difficulty easy,easy,easy,easy,easy,easy \
  --sandbox docker \
  --out runs/groq-glyph
```

Use environment-only credentials:

```bash
export GROQ_API_KEY='...'
python arena.py run \
  --provider groq \
  --model openai/gpt-oss-120b \
  --env glyph \
  --difficulty easy,easy,easy,easy,easy,easy \
  --sandbox docker
```

For an OpenAI-compatible provider without a built-in profile:

```bash
export SUITE_API_KEY='...'
python tools/run_suite.py \
  --manifest suite_manifest.json \
  --provider custom \
  --api-base https://provider.example/v1 \
  --model provider/pinned-model \
  --api-key-env SUITE_API_KEY \
  --sandbox docker \
  --max-cases 1
```

## Artifacts and containers

The controller redacts loaded credentials from provider errors and scheduler
output. API keys must not appear in prompts, traces, manifests, checkpoints,
Docker command arguments, agent environment variables, or judge mounts. The
API client runs on the host; generated agent and judge containers receive only
their workspace/input mounts and no provider credentials.

For CI, store the key in the CI secret store and expose it only to the host
controller job. For Colab/Kaggle, use the platform's secret facility and export
the variable at runtime; never save it in notebook output or a committed
checkpoint.
