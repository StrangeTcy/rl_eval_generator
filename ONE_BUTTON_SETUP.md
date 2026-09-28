# Atria Covering Campaign: One Dispatch, Checkpointed to Completion

## Start the full experiment once

The repository already has a deployed **Atria covering campaign** launcher.
It accepts a `ref` input and checks out that exact branch or commit before it
runs `tools/atria_campaign.py`. This is the bootstrap path when the GitHub
credential cannot modify `.github/workflows/`:

1. Push the tested controller revision (no change to the protected workflow
   path is needed).
2. Open **Actions → Atria covering campaign → Run workflow**.
3. Set `ref` to the pushed revision and dispatch it once.

The controller recognizes that named manual Actions dispatch as the explicit
paid authorization. It writes `campaign_ref.txt` and a non-secret
`campaign_intent.json` before the provider-free gates begin. Scheduled jobs
restore only that recorded revision and intent, then continue it without a
second manual start.

## How a multi-job run reaches completion

GitHub limits one job to six hours. The campaign controller therefore leaves
upload headroom and persists each resume boundary:

1. **Generation preflight** checks every selected case before provider use. The
   current covering selection is 194 cases: 218 inventory cases, minus seven
   reviewed calibration exclusions and 17 unsupported non-text RoPE cases.
2. **Exact-instance gates** atomically bank completed rows in
   `instance_oracles_partial.json`. A gate-wall pause is resumable; the next
   scheduled job validates only missing rows.
3. **Paid episodes** persist `suite_checkpoint.json`. Wall, provider-outage,
   and transient-compatibility pauses resume using the original
   `campaign_ref.txt` and `campaign_intent.json`.
4. **Completion** writes a non-paused checkpoint and completed report. Later
   schedule ticks detect that terminal state and do nothing.

Budget ceilings, failed gates, invalid credentials, Docker failure, and
non-transient provider failures are explicit terminal/operator-stop reasons;
the supervisor never silently raises a ceiling or starts a different campaign.

## Provider-free diagnosis

A local gate-only invocation makes no provider calls:

```bash
python tools/atria_campaign.py \
  --profile experiments/atria_campaign.yaml \
  --out runs/atria_campaign \
  --gates-only
```

A local paid invocation still requires explicit authorization:

```bash
python tools/atria_campaign.py \
  --profile experiments/atria_campaign.yaml \
  --out runs/atria_campaign \
  --allow-provider
```

## Workflow source and bootstrap contract

`.github/workflows/atria-campaign.yml` is the currently deployed executable
launcher. Its `ref` input is deliberately retained as a bootstrap path: it can
run a tested controller revision even when the current GitHub credential may
not modify workflow files.

`docs/workflows/atria-campaign.yml.example` documents the successor workflow
with explicit `paid` / `gates_only` controls. It is not the bootstrap launcher.
The test suite verifies both contracts: the deployed launcher must pin and
checkout the selected `ref`; the documented successor must retain explicit paid
controls and its provider-free/paid separation.
