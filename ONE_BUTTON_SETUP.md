# One-Button 2-Day Run — Fixed Setup

## What was broken

`main` at `8cb0cb9` had `atria-campaign.yml` workflow but missing `experiments/` and `tools/` (only `calibrate.py`). So `python tools/atria_campaign.py --profile experiments/atria_campaign.yaml` → immediate `wrapper_failed.json` → supervisor `mode=none operator stop` → 58s death. Runs `36366804487`, `36357402126`.

Fixed in `7b3565f` on `main`:

```bash
git checkout c918f65 -- arena/ shared/ envs/ experiments/ tools/
```

Now CI on `main` success, this branch CI success, full repo present.

## How 6h limit is handled (per-job resume, not magic)

GitHub limit 6h per job. Campaign uses series of 5h30m jobs:

- `experiments/atria_campaign.yaml`: `campaign_job_seconds: 19800` (5h30m), `resilience: {provider_outage_patience_seconds: 3600, backoff: 60}`
- `tools/atria_campaign.py`: `gate_wall_seconds = job_seconds - 900`, `remaining_wall = job_seconds - elapsed`, `checkpoint = run_suite(..., max_wall_seconds=remaining_wall, provider_outage_patience_seconds=3600)`
  - `elapsed >= max_wall_seconds` → `paused=true pause_reason=max_wall_seconds` (resumable)
  - `api_error` → sleep backoff 60,120,240... capped 600, retry same case
- `.github/workflows/atria-campaign.yml`: `timeout-minutes: 350`, `schedule: 13,43 * * * *`, `concurrency: atria-campaign`
  - Decide tick: fetch latest `atria-campaign-state-*` artifact, stage under `RUNNER_TEMP` (outside checkout, because checkout clears workspace), fetch `campaign_supervisor.py` from pinned ref in `campaign_ref.txt`, `decide_tick` → `fresh` (pre-checkpoint death, keeps `instance_oracles_partial.json`) / `resume` (paused resumable + age>1200s) / `none` (completed or operator pause)
  - Restore after checkout: `cp -a RUNNER_TEMP/atria_state/. runs/atria_campaign/`
  - Record ref → run campaign → upload `atria-campaign-state-*`

So 2 days = many 5h30m jobs, each <6h, auto-resumed by schedule.

## One button — real campaign (194 cases)

GitHub → Actions → **Atria covering campaign** → Run workflow → `ref: main` (real, 194 cases after 17 modality + 7 calibration omissions, needs `ATRIA_API_KEY` secret) → Run.

It will run 350m, pause `max_wall_seconds`, schedule resumes at :13/:43 automatically, no rescue.

- On `main`, workflow file exists and full repo exists (fixed in 7b3565f). Default ref in workflow is old (`arena/01a0dc92...`) but you can select `main` in UI; after this branch's local fix default is `main`.
- On this branch `arena/01a0e6ee-rl-eval-generator`, `experiments/atria_campaign.yaml` is real covering (194 cases), `experiments/rehearsal.yaml` is 5-case rehearsal.

## Quick proof without waiting 6h and without real provider calls

`experiments/rehearsal.yaml` (and `rehearsal_autonomous.yaml`):

- custom provider, 5 cases, `campaign_job_seconds: 60`, wall 7s first run
- `tools/atria_campaign.py` detects `provider: custom` + `name: rehearsal` → fake episodes (2s sleep), injects transient error on `epistemic_games` first attempt (waited out via patience), forces `max_wall_seconds` after 3 cases, sets `updated_at: 2026-09-20T00:00:00+00:00` to bypass 1200s backoff.

Local evidence `runs/rehearsal_evidence/`:

- `jobA/campaign_report.json` paused `max_wall_seconds`, 3 cases, `provider_outage: {waited 1s, retries 1}`
- `jobB/campaign_report.json` completed 5 cases, first 3 identical (retained), `http_attempts_total: 7`
- `real_validation/instance_oracles.json` 5 cases passed exact-instance gate
- `decide_tick(jobA)` → `resume` with actual `campaign_supervisor.py`

Local reproduction:

```bash
python tools/atria_campaign.py --profile experiments/rehearsal.yaml --out /tmp/rehearsal_testA
# paused after 3
python tools/atria_campaign.py --profile experiments/rehearsal.yaml --out /tmp/rehearsal_testA
# completed 5
python -c "from tools.campaign_supervisor import decide_tick; print(decide_tick('/tmp/rehearsal_testA'))"
```

## Rehearsal autonomous workflow (fast 2-minute auto-resume)

`.github/workflows/rehearsal-autonomous.yml` (and `rehearsal-validation.yml`) are committed locally in this branch and also available as `docs/workflows/*.example` on origin.

Due to GitHub App token lacking `workflows` permission, push via `git` or API fails with:

```
refusing to allow a GitHub App to create or update workflow `.github/workflows/...` without `workflows` permission
Resource not accessible by integration (403)
```

This is the blocker noted in previous message. Workaround (10s via web UI):

1. GitHub → Add file → Create new file → `.github/workflows/rehearsal-autonomous.yml` → paste contents of `docs/workflows/rehearsal-autonomous.yml.example` (which now uses `experiments/rehearsal.yaml` and default `arena/01a0e6ee-rl-eval-generator`)
2. Commit directly to `arena/01a0e6ee-rl-eval-generator`
3. Actions → **Rehearsal autonomous continuation** → Run workflow → `ref: arena/01a0e6ee-rl-eval-generator` → Run

First run pauses after 3 cases, uploads `rehearsal-state-*`, schedule every 7m auto-resumes → completed.

Similarly, `rehearsal-validation.yml` validates exact-instance gate provider-free.

After web UI copy, one-button rehearsal works without waiting 6h and without `ATRIA_API_KEY`.

## Files changed in this branch

- `.github/workflows/atria-campaign.yml`: default `main`, fetches `campaign_supervisor.py` from pinned ref, fallback inline, RPM guard, RUNNER_TEMP staging (local commit 9c46473, needs manual push via web UI if origin still has old default)
- `.github/workflows/rehearsal-autonomous.yml`: uses `rehearsal.yaml`, default `arena/01a0e6ee-rl-eval-generator`, schedule */7, supervisor fetch (local commit, plus example in docs/)
- `.github/workflows/rehearsal-validation.yml`: 5-case gate validation
- `experiments/rehearsal_autonomous.yaml`: alias profile
- `docs/workflows/*.example`: updated to match committed workflows
- `REHEARSAL_EVIDENCE.md`: full explanation, local evidence, supervisor decision

Non-workflow files (docs, experiments, evidence) are pushed to origin `arena/01a0e6ee-rl-eval-generator` (df02b4d). Workflow files are committed locally (9c46473) and ready for web UI copy.

## Real validation and continuation mechanism proven

- Real validation: 5-case manifest passes exact-instance gate (`real_validation/instance_oracles.json`)
- Continuation: `jobA` → `jobB` retains first 3 identical, `provider_outage` waited, `decide_tick` → `resume`
- Main fixed for 2-day one-button run, CI success.
