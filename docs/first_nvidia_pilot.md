# Bounded NVIDIA first-five pilot

`experiments/nim_first5.yaml` is the exact five-case, seed-zero pilot plan.
It is intentionally NVIDIA-only and does not assert that its configured model,
account quota, or free entitlement is available. The account must confirm the
exact model ID through `/models` before any completion is sent.

## Credential handoff

Do not paste a credential into chat or place it in the experiment YAML. Use a
private environment variable for the host controller:

```bash
export NVIDIA_API_KEY='set privately in the local shell or secret manager'
```

Alternatively, create the ignored local profile without exposing the key on a
command line:

```bash
python tools/configure_provider.py \
  --provider nvidia \
  --from-env NVIDIA_API_KEY \
  --out secret_key.json \
  --model nvidia/nemotron-3-nano-30b-a3b
```

The helper performs hidden TTY input with `--prompt`, uses atomic private
writes, preserves unrelated profile settings, and refuses to replace an
existing provider key unless `--replace` is explicit. It never accepts a
literal key as an argument.

## Prepare, then execute

Preparation is provider-free until the live handoff. It inventories all
configs, selects only the exact five vectors, generates and compiles each
selected case, runs the zero-call oracle preflight, records the commit and
config hashes, and checks Docker availability:

```bash
python tools/first_experiment.py --out runs/nim_first5
```

A compile-only oracle is not a behavioral verification. Until every selected
judge has a configured, executed reference self-test, this command blocks
**before provider access**. The explicit `--allow-compile-only-oracles` flag
records an operator's decision to proceed without that evidence; see
[`suite_execution.md`](suite_execution.md) and do not treat the override as a
judge fix.

With a clean checkout, a private credential, a working Docker daemon, and an
account preflight that lists the configured model, the same command then does
exactly one bounded completion compatibility check and runs the five cases
serially through `tools/run_suite.py` and `arena.py`. The host controller is
the only API client; Docker agent and judge containers have no network and no
credential mounts.

The profile fixes concurrency at one, 20 maximum agent steps, 8,192 maximum
response tokens, one invalid-action repair per step, no transport retries, a
250-attempt worst-case HTTP budget (including `/models` and the compatibility
request), a two-hour wall-time limit, and disabled floor-effect stopping. Model
answers that score poorly remain recorded; provider/auth/quota, credential,
controller, or isolation failures pause the checkpoint instead of switching
providers or running unsandboxed.

Artifacts are written under the selected output directory, including
`pilot_manifest.json`, `generation_preflight.json`, `oracle_preflight.json`,
`runtime.json`, `provider_preflight.json` when reached,
`compatibility.json` when reached, `suite_checkpoint.json`, and the concise
`pilot_report.json`. Diagnostic provider bodies are sanitized; the preflight
report stores no HTTP response body.
