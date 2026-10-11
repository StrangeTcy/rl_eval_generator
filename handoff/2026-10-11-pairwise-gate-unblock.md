# Pairwise exact-instance gate: state at 2026-10-11 (Europe/Moscow)

Why both pairwise campaigns are parked. `Issue #21` (Mercury) and `Issue #20` (Atria) read
`blocked` / `instance_oracle_coverage_incomplete`. The blocked rows are gate defects, not agent
failures: the exact-instance references were configured per environment and keyed on literal text
that the environments' own axes rewrite.

## What is on `arena/595b91e0-rl-eval-generator` and not on `main`

| commit | what it changes |
| --- | --- |
| `9714d1a` | moco's reference finds its model file by the line it edits (its `naming` axis renames the file, and the `terminology` intervention renames it again); rope and glyph refuse with the axis named instead of a needle count; `tools/instance_oracle_preflight.py`; 13 reviewed omissions in the pairwise profiles |
| `7a12eaa` | glyph's reference splices the whole path into the classifier (removes the 2-D `SpatialEncoderBlock` call and the `SpatialPool(size=4)` coordinate trap from `forward`); the 8 `architecture=hard` omissions are withdrawn - the patch now applies and the shapes are consistent, which is what `tools/instance_oracle_preflight.py` can prove; whether the judge accepts those references is unmeasured here and is the gates_only run's answer; blocked-row reporting grouped by reason x axis so a cut log cannot lose a class |

`main` has neither: `git show main:tools/instance_oracle_gate.py` still opens `moco_model.py` by
name and has no `_glyph_optimizer`. So every cron tick on main re-blocks on the same rows.

## What the two blocked runs actually did, from the job step records

`gh api repos/StrangeTcy/rl_eval_generator/actions/runs/<id>/jobs` gives step conclusions and
timestamps; that is the only account of those runs that is not a reading of a truncated log.

| run | dispatch | `Initialize fresh campaign state` | campaign step | outcome |
| --- | --- | --- | --- | --- |
| `38101874542` Mercury | workflow_dispatch 01:27:03Z | success (so mode=fresh, code = `inputs.ref`) | 01:27:38 -> 03:34:06Z | failure, then state uploaded |
| `38101171391` Atria | schedule, campaign step 01:14 -> 02:13:08Z | skipped (so mode=resume, code = the ref recorded in the state artifact) | 01:27:34 -> 02:13:08Z | failure, then state uploaded |

`Inherit exact-instance gate rows from the covering campaign` succeeded in both, so some gate rows in
those runs may have been inherited rather than computed; the tool also prints a soft
`inheritance failed; the campaign will gate from scratch` and still exits 0, so the step's success
does not establish that anything was inherited.

What is **not** readable from here: which commit each run checked out. Mercury's was whatever
`arena/595b91e0-rl-eval-generator` pointed at when the dispatch was submitted (tip `75b639a`,
committed 01:20:58Z) *only if* the default `ref` was submitted unchanged - the API does not expose a
run's `inputs`. Atria's is the ref inside the state artifact, which lives on
`productionresultssa16.blob.core.windows.net`; `gh run download` reaches a signed URL and then dies
with `EOF` there. So the pin is not established, and the row classes in the pasted logs are
consistent with pre-fix code without proving it.

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

## The `CI` workflow is red, and it is red on `main` too

Measured from `gh api repos/StrangeTcy/rl_eval_generator/actions/runs/<id>/jobs` step timestamps:

```
dd31840 (this branch) : job smoke 13:04:28Z -> 13:04:37Z, step "Run pytest -q" failure, elapsed 2s
f3f7097 (main)         : job smoke 22:36:06Z -> 22:36:17Z, step "Run pytest -q" failure, elapsed 2s
```

Two seconds means pytest never reached a test: `.github/workflows/ci.yml` runs `pip install -r
requirements.txt` then `pytest -q`, and the step exits 2 at startup. Ruled out by measurement, not
by taste: the root-level `test_cat_theo.py` / `test_weird_machine.py` scripts are not collected
(`pyproject.toml:54-56` sets `testpaths = ["tests"]`), and there is no `conftest.py` anywhere in
the tracked tree (`git ls-files | grep conftest` is empty, 0 lines back). Reproducing CI on a clean
checkout - `git archive HEAD | tar -x -C /tmp/ci_tree`, then `.venv/bin/python -m pytest -q` - runs
663 tests for over two minutes with no failures, so the startup error is specific to the runner
environment. The difference I can name is that `setup-python` installs into an image that already
carries plugins, while a bare venv gets only `PyYAML` and `pytest` from `requirements.txt`. Naming
the module needs the 2-second log, which is one click for you and unreachable from this sandbox
(the log endpoint redirects to a blob host this network refuses).

Consequence to keep straight: until that startup failure is fixed, `CI` says nothing about any
commit on this branch, including the T1 refusal and the guard fix below. Local full-suite results
are the only green this branch currently has.

## Guard test `test_a_chained_campaign_presents_a_resume_as_a_resume` - fixed at `dd31840`

This was a real failure on this branch's chain (`3f11513`, `294539f`, `0b66319`, `332c8c9`), and
it was reproducible here while CI's red was not. Cause read from the files: `.github/workflows/
atria-campaign.yml` has the chain step (line 757) and presents an explicit resume by unsetting the
variable for the controller process - `env -u GITHUB_EVENT_NAME python tools/atria_campaign.py` at
line 661, with the policy comment at line 658 ("never override GITHUB_EVENT_NAME in the workflow
env") - while the test accepted only a step-level `GITHUB_EVENT_NAME` override. Measured across the
copies: live `chain=1 env-u=1 override=0`; `docs/workflows/atria-campaign.yml.example`
`chain=0` (so it is skipped); the chained example carries the override; all four pairwise copies
have `chain=0`.

Both mechanisms give the controller what it needs, and the unset is the stronger one:
`_should_reset_output` reads a missing variable as `event local is a resume`
(`tools/atria_campaign.py:954-955`) so there is no template for a runner to resolve wrongly, and it
still refuses to wipe when recorded episodes exist (`:957-961`). The assertion now names the outcome
- a chained campaign must present its resume as a resume by either mechanism - and fails with the
wipe it prevents when a workflow presents neither. The live file was never a place to fix this: this
branch cannot push to `.github/workflows/` (the automation token has no `workflows` permission, per
the guard's own docstring), so the test moved. Verified: `pytest tests/test_campaign_workflow_guard.py
-q` -> 6 passed; bare `pytest -q` on this tree -> no failures (511 s).

## Two known open items, neither of them a gate weakening

- T1 replay after an interruption. The launcher's T1 block guarded only on the absence of
  `$OUT/t1_same_fact_presentation.json`, while its cleanup trap writes `$OUT/t1_interrupted.json`
  declaring `operator_review_required_no_replay` - which nothing read. So a tick after an
  interrupted T1 replayed the probe (paid, up to 4200 s) instead of stopping. The pairwise
  launcher copies now refuse inside the paid branch; the covering pair must take the same 13
  lines in both `.github/workflows/` and `docs/workflows/` at once, because
  `test_deployed_and_documented_covering_workflows_share_the_wall_budget` pins those two files
  to equality. `tools/run_suite.py` is not involved: it has no T1 machinery at all (`grep -c t1`
  returns 0 there), which is also why the `campaign_preflight.py` story in an earlier handoff
  note of mine was wrong - no such file exists.
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
