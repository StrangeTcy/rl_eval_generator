# One-Button 2-Day Run — Fixed Setup (including 38s checkout fix)

## What was broken

`main` at `8cb0cb9` had `atria-campaign.yml` workflow but missing `experiments/` and `tools/` (only `calibrate.py`). So `python tools/atria_campaign.py --profile experiments/atria_campaign.yaml` → immediate `wrapper_failed.json` → supervisor `mode=none operator stop` → 58s death. Runs `36366804487`, `36357402126`.

Fixed in `7b3565f` on `main`: `git checkout c918f65 -- arena/ shared/ envs/ experiments/ tools/`

Then you dispatched at `7b3565f` and got **38s death at checkout** (run `36393386990`):

```
Check out pinned campaign code failure (28s)
```

Root cause of 38s: workflow file at `7b3565f` has default `ref: arena/01a0dc92-rl-eval-generator` (old branch without exclusions) and checkout with `fetch-depth: 1` (default). If input `ref` is a commit SHA from another branch (e.g. `f117b73` from `arena/01a0e6ee`), shallow fetch fails with "not found" in 38s.

Also old artifacts `atria-campaign-state-1..12` from pre-fix lack `manual_gate_blocked_exclusions` and always die with `gate_case_repeatedly_blocked` after 40m. Schedule ticks kept trying to resume them (run `36392902414` 1m6s failure at campaign step).

## Fixes applied locally (need web UI copy due to App token lacking workflows permission)

`.github/workflows/atria-campaign.yml` (local `dddff76` → now with fetch-depth 0 fix):

- default `ref: main` (was old `arena/01a0dc92`)
- checkout `fetch-depth: 0` — required because pinned ref may be commit SHA from another branch not in main's shallow history; without it checkout fails 38s (run 36393386990)
- old artifact guard: fetch `experiments/atria_campaign.yaml` at pinned ref via `gh api`, if it lacks `manual_gate_blocked_exclusions` (pre-7b3565f) → `mode=none reason=old campaign state without exclusions, dispatch fresh with ref: main` — prevents schedule ticks from endlessly retrying broken pre-fix artifacts
- supervisor fetch from pinned ref `campaign_supervisor.py` (versioned together), fallback inline logic, RPM guard

`.github/workflows/rehearsal-autonomous.yml`: same fetch-depth 0 fix, uses `rehearsal.yaml`, default `arena/01a0e6ee-rl-eval-generator`, schedule `*/7`.

Both files are in `docs/workflows/*.example` on origin (pushed) and locally in `.github/workflows/` (cannot be pushed via App token: `refusing ... without workflows permission` / 403).

**10s web UI workaround:**

1. GitHub → main branch → `.github/workflows/atria-campaign.yml` → Edit → paste fixed version from `docs/workflows/atria-campaign.yml.example` (default main, fetch-depth 0, old artifact guard) → Commit directly to main
2. GitHub → Add file → `.github/workflows/rehearsal-autonomous.yml` → paste `docs/workflows/rehearsal-autonomous.yml.example` → Commit to `arena/01a0e6ee-rl-eval-generator`
3. Delete old artifacts via web UI: Actions → Artifacts → delete `atria-campaign-state-1..12` (or they will be ignored by new guard, but cleaner to delete)

## One button — real 2-day run (after web UI fix)

Actions → **Atria covering campaign** → Run workflow → `ref: main` (194 cases, needs `ATRIA_API_KEY`) → Run.

It will run 350m, pause `max_wall_seconds`, upload state, schedule resumes at :13/:43 automatically.

- `experiments/atria_campaign.yaml`: `campaign_job_seconds: 19800` (5h30m), `resilience: {patience 3600, backoff 60}`
- `tools/atria_campaign.py`: `gate_wall = job -900`, `remaining_wall = job - elapsed`, `run_suite(max_wall_seconds=remaining_wall, patience=3600)` → `paused=true pause_reason=max_wall_seconds` resumable, `api_error` → backoff 60,120,240 capped 600 retry
- Per-job resume: 2 days = many 5h30m jobs, each <6h, auto-resumed

GitHub UI shows `failure` for paused runs (exit 8) — check `campaign_report.json` `status: paused, resumable: true`.

## Quick proof without 6h and without API key

`experiments/rehearsal.yaml`: custom provider, 5 cases, `campaign_job_seconds: 60`, wall 7s first run, fake episodes 2s, transient error on `epistemic_games` first attempt (patience 60/backoff 1), forces `max_wall_seconds` after 3 cases, `updated_at: 2026-09-20` bypasses 1200s backoff.

Local evidence `runs/rehearsal_evidence/`:
- `jobA` paused 3 cases `provider_outage {waited 1s retries 1}`
- `jobB` completed 5 cases first 3 identical retained `http_attempts_total: 7`
- `real_validation/instance_oracles.json` 5 cases passed exact-instance gate
- `decide_tick(jobA)` → `resume` via real `campaign_supervisor.py`

Rehearsal one-button (after web UI copy): Actions → **Rehearsal autonomous continuation** → Run workflow → `ref: arena/01a0e6ee-rl-eval-generator` → Run → first run pauses, second scheduled run completes in ~2 min total.

## Files

- `docs/workflows/atria-campaign.yml.example` = fixed real workflow (pushed to origin)
- `docs/workflows/rehearsal-autonomous.yml.example` = fixed rehearsal workflow (pushed)
- `.github/workflows/atria-campaign.yml` local fix with fetch-depth 0 + old artifact guard (needs web UI copy to main)
- `.github/workflows/rehearsal-autonomous.yml` local fix (needs web UI copy to arena/01a0e6ee)
- `REHEARSAL_EVIDENCE.md` updated
