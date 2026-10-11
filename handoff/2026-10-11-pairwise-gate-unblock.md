# Pairwise exact-instance gate: state at 2026-10-11 (Europe/Moscow)

Why both pairwise campaigns are parked. `Issue #21` (Mercury) and `Issue #20` (Atria) read
`blocked` / `instance_oracle_coverage_incomplete`. The blocked rows are gate defects, not agent
failures: the exact-instance references were configured per environment and keyed on literal text
that the environments' own axes rewrite.

## What is on `arena/595b91e0-rl-eval-generator` and not on `main`

| commit | what it changes |
| --- | --- |
| `9714d1a` | moco's reference finds its model file by the line it edits (its `naming` axis renames the file, and the `terminology` intervention renames it again); rope and glyph refuse with the axis named instead of a needle count; `tools/instance_oracle_preflight.py`; 13 reviewed omissions in the pairwise profiles |
| `7a12eaa` | glyph's reference splices the whole path into the classifier (removes the 2-D `SpatialEncoderBlock` call and the `SpatialPool(size=4)` coordinate trap from `forward`); the 8 `architecture=hard` omissions are withdrawn because that fix makes them certifiable again; blocked-row reporting grouped by reason x axis so a cut log cannot lose a class |

`main` has neither: `git show main:tools/instance_oracle_gate.py` still opens `moco_model.py` by
name and has no `_glyph_optimizer`. So every cron tick on main re-blocks on the same rows.

## Verified in the sandbox, with the command that produced it

- `python3 -m venv .venv && .venv/bin/pip install -q pyyaml pytest` (the venv is not persisted).
- `.venv/bin/python tools/instance_oracle_preflight.py --profile experiments/mercury_pairwise_campaign.yaml`
  -> `gated cases probed: 255 of 482` and `every gated case is reachable by its reference`, exit 0, 88 s.
  Same result for `experiments/reasoning_atria_pairwise_campaign.yaml` and for
  `experiments/mercury_covering_campaign.yaml` (88 of 233).
- Before `9714d1a`, the same probe on the same plan reported 70 unreachable cases: 65 moco
  `FileNotFoundError`, 5 rope `ValueError`. It ran against the plan of 260 gated cases.
- `.venv/bin/python -m pytest tests/test_instance_oracle_reference.py tests/test_atria_campaign.py -q`
  -> 32 passed. Full suite -> one failure, pre-existing and unrelated:
  `tests/test_campaign_workflow_guard.py::test_a_chained_campaign_presents_a_resume_as_a_resume`,
  which asserts that `.github/workflows/atria-campaign.yml`'s campaign step overrides
  `GITHUB_EVENT_NAME` for a resume; that file is identical on main and here, so main is red on it too.

## Not verified, and not verifiable in this sandbox

Whether the judge *grades* the repaired references as expected - the 65 moco cases and the 8 glyph
`architecture=hard` cases. There is no torch and no judge image here, which is exactly why
`tools/instance_oracle_preflight.py` is a patchability check only and prints that caveat. The run
that answers it is free of provider cost:

1. Actions -> `Mercury pairwise campaign` -> Run workflow
2. `ref` = `main` (after the merge below), `execution_mode` = `gates_only`, `resume_previous` = unchecked
3. Read `runs/mercury_pairwise_campaign/instance_oracles.json`, not the step log's truncated tail

## Merging, and what to paste afterwards

Measured with the compare API (`git merge-base` is unavailable here: the sandbox clone is shallow and
shows `main` as a single parentless commit):

    gh api repos/StrangeTcy/rl_eval_generator/compare/main...arena/595b91e0-rl-eval-generator
    status=diverged  ahead_by=18  behind_by=4  merge_base=5bd367a  files=48

ahead_by counts this file's own commit too, so it moves whenever the branch moves.
Main's four commits since that base touch 4 paths - `tools/atria_campaign.py`, and the three workflow
adds - so exactly one path is changed on both sides. That one is not a competing edit: both sides pass
`max_output_tokens` to `complete_responses` and `max_tokens` to `complete`, which is main's
`4ea16a6` fix for the Responses client; this branch carries the same keyword choice and adds the
comment saying why (`diff` of the two `_compatibility_check` bodies shows only those comment lines).
So merging cannot bury that fix, and main's `.github/workflows/*-pairwise-campaign.yml` stay as they
are, because this branch deliberately does not carry live workflow copies.

Keep the branch after merging. Arena tracks this session by branch name and follow-ups push here, so a
deleted branch strands whatever is still open below.

Optional but recommended: the preflight guard, so a stale reference costs a minute instead of a
tick. Paste into `.github/workflows/mercury-pairwise-campaign.yml` and the reasoning-atria twin,
immediately before the step `Run T1 and pairwise campaign with live Issue status`:

```yaml
      - name: Refuse a plan whose exact-instance reference cannot be applied
        if: steps.mode.outputs.mode == 'fresh'
        run: |
          set -euo pipefail
          .venv/bin/python tools/instance_oracle_preflight.py \
            --profile experiments/mercury_pairwise_campaign.yaml \
            --out runs/mercury_pairwise_campaign/instance_oracle_preflight.json
```

`handoff/mercury-pairwise-campaign.yml` and `handoff/reasoning-atria-pairwise-campaign.yml` already
carry that step inside a complete file, with comments, if a whole-file copy is easier.

## Two known open items, neither of them a gate weakening

- `t1: gate`. `tools/run_suite.py` has no handling for it, so a `paid` tick whose T1 phase is
  incomplete still pauses rather than skipping T1 - the 108-minute idle shape. The change is: accept
  `t1: gate` in the pairwise profiles, refuse in `run_suite.py` when T1 is incomplete and neither
  `--execute-t1` nor `--t1-plan-file` is supplied, and skip the T1 block in `campaign_preflight`
  for that value. Not shipped here because it cannot be exercised against a live runner from this
  sandbox.
- Plan size against the ceiling you set: 482 cases x 40 calls / 327,680 tokens reserves about
  158 M tokens against `max_tokens_total: 136000000`, i.e. roughly 415 cases fit. That is a sizing
  decision, and budget pauses are not in `RESUMABLE_PAUSE_REASONS`, so a ceiling stop is terminal
  for the cron loop.

## Files that are deliberately uncommitted in the sandbox

`.github/workflows/*-covering-campaign.yml` differ here (they carry the `resume_previous` input and
the 330-minute budget block). Their content is already committed at `handoff/mercury-covering-campaign.yml`
and `handoff/reasoning-atria-covering-campaign.yml` - byte-identical - so nothing is lost if this
sandbox goes away; main's mercury covering copy still lacks the input, which is the one difference
that matters for that campaign's resume path.
