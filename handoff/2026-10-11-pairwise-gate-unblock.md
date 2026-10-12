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

## "And in a couple of hours it dies again" - the root cause, found and fixed

The dispatcher click was never the whole story, and the reason is a cache-invalidation
bug, not a hard problem. Read from these lines:

- `tools/run_suite.py:656-660` states the gate phase "can cost more CPU-hours than one
  runner job (Glyph/MoCo reference training dominates)", so rows accumulate per case into
  `instance_oracles_partial.json` and a resume revalidates only the missing ones.
- `tools/run_suite.py:666` accepts a banked row only when its `gate_context_sha` equals the
  current one, and `tools/atria_campaign.py:96` computed that context as
  `git rev-parse HEAD` - the whole-repository revision.
- `tools/inherit_campaign_state.py` refused to re-key rows across contexts on purpose
  ("Gate rows get no such exception - accepting a row produced by different grading code
  would launder the guard").

Put together: every commit - including a commit to a handoff note, a launcher comment, or a
test - invalidated 100% of the banked gate rows, and the 255 gated rows of the 482-case plan
restarted from zero. A campaign that ticks on cron while the repository is being edited
therefore cannot finish gating, whatever it gates correctly. `GateCaseBlockedRepeatedly`
(two failures across dispatches, `run_suite.py:690-700`) never fired either, because a context
mismatch drops the whole row dict including the attempt counters (`partial_rows = {}`).
The death loop was structural.

Fix: the gate context is now the digest of the verdict-producing file set - the transitive
import closure of `run_suite`, `instance_oracle_gate`, `instance_oracle_preflight`,
`suite_inventory`, plus every file under `envs/` and the root `requirements.txt` - computed by
the new `tools/gate_context.py` and returned by `_gate_context_sha()`. Measured on this tree:
296 files, 297 counting `gate_context.py` itself. `tools/gate_context.py --json` prints the
inventory and per-file digests for auditing. Properties pinned by `tests/test_gate_context.py`:
a README/workflow/handoff edit leaves the digest unchanged; an edit to `envs/glyph/config.yaml`,
`tools/instance_oracle_gate.py`, `arena.py` or `requirements.txt` moves it; a module that the
gate newly imports is covered without touching the list (that bug was caught by the test: seeds
listed in both places were skipped before their imports were read); a missing input raises
instead of hashing a smaller set.

Two honest limits, both measured rather than assumed:

- `tools/atria_campaign.py` is inside the context (something in the closure imports it), so
  controller edits still re-gate. Demonstrated by the diff itself: comparing this tree against
  `c4b8e8f` reported `changed content: ['tools/atria_campaign.py']`. That is over-strict, kept
  deliberately, and the note is that this commit re-gates once - after it, only grading-path
  changes do.
- The other half of the loop - `tools/campaign_supervisor.py` resuming pinned to
  `checkpoint.run.manifest_commit`, so a running campaign keeps running the code it started with -
  is now handled for the one thing it made unreachable: the spend ceilings. See the next section.
  A fresh dispatch remains the only way to pick up *code* changes, and it still costs the episode
  ledger (gate rows now survive any commit that does not touch grading code).

Verified on this tree: `pytest tests/test_gate_context.py tests/test_inherit_campaign_state.py
tests/test_atria_campaign.py tests/test_campaign_supervisor.py
tests/test_exhaustive_campaign_recovery.py tests/test_campaign_completion_contract.py
tests/test_paid_campaign_safety.py -q` -> 52 passed; full `pytest -q` -> no failures in 511 s.

## Death B: the budget stop, and the way out that costs no commit

The gate was not the only way a campaign dies after a couple of hours. Measured in this tree:

- `tools/run_suite.py:1049-1064` records `pause_reason` as `max_api_calls`, `max_tokens_total`,
  `max_output_tokens` or `max_http_attempts` when a ceiling is reached.
- None of those is in `RESUMABLE_PAUSE_REASONS` (`tools/campaign_supervisor.py:23-33`), so the
  supervisor returned `operator pause: max_tokens_total (supervisor never raises ceilings)` and the
  cron loop stopped retrying. That refusal is correct as policy - the machine must not spend more
  than the operator approved.
- The dead end was in the escape hatch. `max_tokens_total` and `max_api_calls` are inside
  `_load_checkpoint`'s `immutable` tuple (`tools/run_suite.py:236-256`), so raising the profile
  number and resuming failed with `checkpoint metadata mismatch for max_tokens_total`; the profile
  lives in the commit the campaign is pinned to, so a bump needs a commit; and the only way to run
  a new commit is a fresh dispatch, which discards the accumulated ledger. There was no path at
  all: every route either refused or destroyed work.

Shipped instead: the ceiling is a dispatcher input, and the authorisation is written where the rows
it buys are.

- `tools/atria_campaign.py`: `--limit KEY=INTEGER` (repeatable, `KEY` in
  `max_api_calls, max_tokens_total, max_http_attempts`) merged over the profile without rewriting
  the profile, plus `--raise-ceiling HANDLE`.
- `tools/run_suite.py`: `CEILING_FIELDS` are the only immutable checkpoint fields allowed to change,
  only upward, only with an authorising handle, and every such raise is appended to
  `suite_checkpoint.json` as `ceiling_raises` (`field / from / to / authorized_by / at`) so the
  spend history of a leg is readable from the state artifact. A reduction is refused, `model`,
  `provider`, `api_base`, `wire_api`, `reasoning_effort`, `max_tokens` and the rest still refuse,
  and `max_output_tokens` is deliberately *not* liftable because it is part of the request shape,
  not the budget.
- `tools/campaign_supervisor.py`: a ceiling pause resumes only when the dispatched value exceeds
  the recorded one (`_ceiling_was_raised`), the refusal message now names that action, and a
  checkpoint without a recorded ceiling is refused rather than guessed at.
- All four pairwise launcher copies gained `max_tokens_total_override` and `max_api_calls_override`
  inputs, pass them as `LIMIT_ARGS` to the paid command only (with `--raise-ceiling
  "$GITHUB_ACTOR"`), probe the pinned supervisor's signature with `inspect` so an older revision is
  not handed an argument that would crash the mode decision, and refuse the leg in
  `Refuse code missing campaign gates` when the pinned ref has no `def _apply_limit_overrides` -
  silently ignoring an operator's authorisation is the worst available outcome.

The number itself is yours, not mine. For the current profiles: `max_tokens_total: 136000000` at
327,680 output tokens per case pays 415 cases, and the pairwise plan is 482, so a full sweep wants
about 158M; `max_api_calls: 21200` is not the binding ceiling (530 cases at 40 calls). Dispatching
`max_tokens_total_override=160000000` buys the remaining 67 cases against the campaign that already
has the gate rows; raising nothing stops after 415.

Verified on this tree: `tests/test_ceiling_override.py` 15 passed (supervisor lift/no-lift,
checkpoint accept/refuse/append, CLI validation); `pytest tests/test_provider_reasoning_campaigns.py
tests/test_ceiling_override.py tests/test_campaign_supervisor.py -q` 59 passed; every step body of
all four launchers `bash -n` clean (10 and 11 run-steps per file) and YAML-parsing with
`inputs=[ref, execution_mode, resume_previous, max_tokens_total_override, max_api_calls_override]`;
full `pytest -q` no failures in 524 s.

## The launcher I shipped killed the first leg: `LIMIT_ARGS: unbound variable`

Reported from the runner after the manual paste of `handoff/mercury-pairwise-campaign.yml` into
`.github/workflows/mercury-pairwise-campaign.yml` (main `057ad23`, verified byte-identical to my
copy by diff = 0 lines):

```
/home/runner/work/_temp/8b4dc55c-....sh: line 69: LIMIT_ARGS: unbound variable
Mercury campaign budget: elapsed=501s profile_max=19800s effective=19239s
Error: Process completed with exit code 1.
```

Two defects, both mine, both in the workflow file rather than in the campaign code:

1. **A shell variable does not cross a step boundary.** I built `LIMIT_ARGS` in
   `Decide fresh dispatch versus supervised resume` (file lines 121-126) and expanded it in
   `Run T1 and pairwise campaign with live Issue status` (line 370). Each `run:` block is its own
   `bash` process, so the second step never declared it and `set -u` aborted the leg - after the
   budget line, before the campaign command, so nothing was billed and the state artifact still
   uploaded (`Stage campaign state for upload` is `if: always()`), which is why the lineage is not
   lost.
2. **A Python `.format()` call ate a brace pair.** The mode-step block came from a template
   formatted with `provider=%s`, so `${{ inputs.max_tokens_total_override }}` was emitted as
   `${ inputs.max_tokens_total_override }`. GitHub only substitutes double-brace expressions, and
   bash's "bad substitution" inside an `if` condition does not trip `set -e` - so the step survived
   with an empty array and a *real* ceiling override would have been dropped silently in the mode
   decision. Fixed on both sides.

Now: each step that touches the array declares it (`declares=1, references=3` in the mode step and
`declares=1, references=6` in the campaign step, measured by parsing the YAML), the expansion uses
the nounset-safe `${LIMIT_ARGS[@]+"${LIMIT_ARGS[@]}"}` form that an empty array needs on a
scheduled tick, and `tests/test_provider_reasoning_campaigns.py` *executes* the campaign step's own
lines - blank inputs (asserts rc 0 and no arguments), filled (asserts exactly
`--limit max_tokens_total=160000000 --limit max_api_calls=30000 --raise-ceiling tester`), and a
single input - plus a static rule that no run body may contain a single-brace `${{ }}`-looking
expression. Verified: 38 passed in that file; all four launcher copies YAML-parse with 10/11/13/14
steps and zero `bash -n` failures.

Lesson kept: the launcher text is not documentation, it is code, and "the YAML parses and
`bash -n` is clean" does not test that a variable exists where it is read.

## First runner-produced gate diagnostics: 195 blocked rows -> 12, and what they still do not say

Read from the Reasoning-Atria leg at `17:5x` on head `32c5f3a` (the fixed launcher): it banked
`7 / 189` gate rows, then exited 2 with

```
atria campaign failed: exact-instance behavioral oracle coverage is incomplete; inspect
runs/reasoning_atria_pairwise_campaign/instance_oracles.json before any paid call
12 blocked exact-instance oracle row(s), 6 group(s): reference_did_not_grade_as_expected ...
```

What that establishes, with no inference added: the launcher fix worked (the campaign step ran for
41 minutes of gate work instead of dying at line 69); T1 was not re-billed (`72 / 72` calls came
from the banked marker); the paid phase was never reached, so nothing was spent; and the
`architecture=hard` / 2-D-pooling class that blocked 195 rows is down to 12 rows, all `glyph`,
all `reference_did_not_grade_as_expected`, in 6 axis groups each appearing twice (a base case and
its `__visible_proxy` twin).

What it does not establish, and why: the reference criterion is `verdict == "PASS"`, `score == 1.0`,
`failure_mode == "pass"`, `patch_valid` (`tools/instance_oracle_gate.py:549-550`), and one reason
string covers both "the reference did not reach a perfect score" and "the reference program is
broken". Those have opposite repairs - raise the training budget, or fix the splice - so the row
was made to record the judge's actual return: `observed` with variant, done, verdict, score,
raw_accuracy, failure_mode, the checks that came back False, the last three judge notes,
elapsed_seconds and a 400-char stderr tail (`8121377`). The campaign summary prints one `saw:`
line per group, and the 6000-character cut became `DIAGNOSTIC_CHAR_LIMIT = 12000` with an explicit
`cut at N chars, M further line(s)` notice, because a silent cut is what once made a 49-row
failure set get read as 14 rows.

No exclusions were written, and the profiles' existing ones are now counted in a test. Both
pairwise profiles ship 8 glyph rows under `reference_does_not_solve_its_own_instance`, plus three
classes the tool never emits: `reference_exists_per_environment_not_per_vector`,
`oracle_assumes_easy_layout`, and `reference_fix_already_present_at_symptom_mask_hard`. That last
claim is the one to test next, because two of today's six groups are `symptom_mask=hard` rows.
`tests/test_gate_failure_diagnostics.py` pins the ceiling at 8 so a ninth cannot be added without
a failing test, requires every omission to state a class, and forbids new hand-written vocabulary.

Cost of the change, stated: `tools/instance_oracle_gate.py` is inside the gate context, so the
next leg re-gates the 7 rows Atria already banked. That is the same mechanism that used to destroy
everything on a documentation commit, now firing only for a real grading-code edit - once, and
provably because the grader changed.

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


## A code fix cannot reach a campaign on the next tick - what "continue now" actually costs

Written after the glyph reference fix (`4ca1123`), because I told the operator in chat that the
`:13`/`:43` tick would "check this branch out again and pick the fix up". It will not, and the
sentence was wrong: `decide_tick` resumes at the commit the state was *created* from, not at the
ref string - `resume_ref = checkpoint.run.manifest_commit or recorded_ref`
(`tools/campaign_supervisor.py:302-303`, with the comment above it explaining why a branch name is
not trustworthy: "it cannot have moved since the dispatch"). The same pin applies to the
interrupted-active-worker path at `:256-258`. So every cron tick after a push re-runs the code that
produced the banked rows; a fix that lives only in the repo is invisible to a resumed campaign.

The other half: a gate wall is not resumable by design. A `pause_reason` outside
`RESUMABLE_PAUSE_REASONS` returns `mode=none` with "operator pause: ..."
(`tools/campaign_supervisor.py:274-282`), and a `mode=none` leg skips every step and exits 0 -
which is what Atria's scheduled leg at 19:32Z was: green, and doing nothing.

So continuing a blocked campaign means one manual `workflow_dispatch`, and the fresh branch is the
first thing the mode step tests: `workflow_dispatch` + `resume_previous != "true"` takes `ref` and
`execution_mode` straight from the inputs and reports `mode=fresh`
(deployed `.github/workflows/reasoning-atria-pairwise-campaign.yml:85-90`). The values, for either
pairwise campaign:

    ref             arena/595b91e0-rl-eval-generator
    execution_mode  paid
    resume_previous false

`gates_only` is the wrong pick even though the next hours are all gating: the mode is read back only
from the persisted intent, so a lineage that starts `gates_only` can never be promoted to paid by a
resume, while `paid` itself costs nothing until the gate wall passes (the wall runs before any
credential is resolved - `tools/run_suite.py:655-670`).

What fresh throws away, measured rather than guessed: gate rows are reused only when
`gated_manifest_sha256` *and* `gate_context_sha` both match (`tools/run_suite.py:715-720`, partial
resume at `:737`). Editing any grading code moves `gate_context_sha`, so the 126 rows Atria banked
and the rows Mercury was banking were already unreachable the moment the diagnostics landed at
`8121377` - the reference fix did not create that cost, it paid it once more. Re-grading is
provider-free at 2-4 minutes a row over the 269 gated rows, i.e. several legs of the 330-minute
live step.

And the dispatch itself is an operator action from here: `gh workflow run
reasoning-atria-pairwise-campaign.yml --ref main -f ref=... -f execution_mode=paid -f
resume_previous=false` from this sandbox returns `HTTP 403: Resource not accessible by integration`
on `POST /actions/workflows/380866773/dispatches`. Same reason the launcher header already records
for creating workflow files: the credential this session holds is read-scoped for Actions, so it
can push code and read runs, and cannot start them.


## Mercury's leg produced the same 12 rows, independently, on the same axis pair

The operator pasted the leg that started at 19:33Z: 12 blocked rows, 6 groups, every one of them
`red_herring=hard` or `symptom_mask=hard` (`hard/hard/hard/hard/hard/hard`,
`hard/medium/hard/medium/hard/medium`, `medium/medium/easy/easy/hard/hard`,
`medium/hard/medium/hard/medium/hard`, `medium/medium/hard/hard/easy/easy`,
`easy/hard/easy/hard/easy/hard`), each as a base case and its `__visible_proxy` twin. That is the
same six vectors Atria's artifact carried, from a different runner, a different provider and a
different leg - the boundary the fix at `4ca1123` is built on is no longer resting on one artifact.
This leg predates the fix and resumes at its own pinned commit, so it is confirmation of the
*boundary*, not a verdict on the repair; only a leg started at a ref that carries it can be that.

The log ended by offering the recipe: `to omit them, add under manual_gate_blocked_exclusions.cases`
with `calibration_class: reference_does_not_solve_its_own_instance`. Not taken. Writing twelve
exclusion lines converts a reference defect into a permanent coverage hole and makes the campaign
green for the wrong reason; the two data-pipeline repairs are the answer, and they are in the repo.

### The silence that made "wait for the tick" look reasonable is now an annotation

`mode=none` skips every step and exits 0, which is how a refusal to resume and a successful
continuation became the same colour in the runs list. Both pairwise launchers now carry one step,
directly after the step that decides the mode, that emits the supervisor's reason as a
`::warning::` annotation and stays green - visible in the Checks UI and via
`GET /actions/runs/<id>/jobs`, so a resume claim can be contradicted by one tick. Pinned by
`tests/test_pairwise_matrix.py::test_a_refused_tick_announces_itself_and_stays_green`, which asserts
the placement, the `mode == 'none'` guard, that the reason reaches the shell through `env` rather
than interpolation, and the absence of any `exit 1`/`failure` in the step. The covering pair is
deliberately untouched: its `.github/workflows` copies are dirty in this sandbox and an equality
pin there would turn a green suite red over a cosmetic half-edit.

## Files that are deliberately uncommitted in the sandbox

`.github/workflows/*-covering-campaign.yml` differ here (they carry the `resume_previous` input and
the 330-minute budget block). Their content is already committed at `handoff/mercury-covering-campaign.yml`
and `handoff/reasoning-atria-covering-campaign.yml` - byte-identical - so nothing is lost if this
sandbox goes away; main's mercury covering copy still lacks the input, which is the one difference
that matters for that campaign's resume path.

## The rebase dispatch: a fix can now reach a campaign without throwing its ledger away

Everything above this section describes the forced choice: a resume re-runs the commit pinned in its
own state artifact (`resume_ref = checkpoint.run.manifest_commit or recorded_ref`,
`tools/campaign_supervisor.py`), so it can never carry a fix; a fresh dispatch takes the new ref and
discards the paid T1 result, the episode ledger and the ceiling counters, then re-bills T1. Both are
correct as safety properties - a lineage must not silently change what it measures - so the answer is
a third path that is explicitly authorized at both ends, added on 2026-10-11:

- New launcher input `rebase_onto_ref` (empty by default) in both pairwise launchers. A
  `workflow_dispatch` with it set decides `mode=rebase`: `ref` comes from the input, every other step
  runs unchanged, and the controller call gains `--rebase-intent`.
- `tools/atria_campaign.py` accepts that flag inside `_record_campaign_intent` only when the drifted
  intent field is *exactly* `gate_context_sha`, and only when `GITHUB_EVENT_NAME` is
  `workflow_dispatch`. It then rewrites the intent and records the previous digest as
  `rebased_from_gate_context_sha` plus `rebased_at`/`rebased_by`, so the rows graded after a rebase are
  attributable instead of being quietly compared against a stale digest. Any other drift - provider,
  model, endpoint, effort, execution mode, manifest, profile identity - still raises, and the message
  now names which fields changed.
- The mode stays whatever the carried intent says. A rebase cannot promote a `gates_only` lineage or
  demote a paid one, because the branch reads `execution_mode` out of `campaign_intent.json`, not out
  of the dropdown.
- Two carried states are refused outright, each with the reason in the leg's output: an interrupted T1
  (`t1_started.json` without `t1_same_fact_presentation.json`) and a recorded terminal failure
  (`wrapper_failed.json`, the same file `tools/inherit_campaign_state.py` keeps in `NOT_INHERITED`).
  A corrupt or unreadable intent is also refused rather than guessed at, and `jq` failures inside that
  check are swallowed on purpose so the refusal branch is what reports the problem.
- With no state artifact, or one without an intent, the rebase degrades to a plain fresh dispatch and
  says so in the reason - it never fabricates a carried authorization.
- Because a rebase runs new grading code, the provider-free preflight step ("Refuse a plan whose
  exact-instance reference cannot be applied") now fires on `fresh` *and* `rebase`; the fresh-state
  initializer deliberately stays `fresh`-only, so a rebase keeps the ledger it was given.
- Gate rows are still re-graded after a rebase, by design: they are keyed on `gate_context_sha`, which
  is what just moved. What the rebase saves is the *paid* part - T1's 72 matched-arm calls and every
  recorded episode row - not the free part.

What is **not** solved by this file: the launcher that actually runs lives in
`.github/workflows/` on `main`, and GitHub refuses any push from this session's App credential that
creates or updates a workflow path (`refusing to allow a GitHub App to create or update workflow
'.github/workflows/mercury-covering-campaign.yml' without 'workflows' permission`, measured when I
tried to commit the covering copies). So the input exists for a campaign the moment the operator pastes
`handoff/<name>-pairwise-campaign.yml` over `main`'s copy; until then a rebase dispatch simply has no
field to fill in.

## 2026-10-12 (late): what the 189-row wall actually is, and what it proves

Reproduced provider-free from this repository's own functions, at `5579aa4`:

| step | function | cases |
|---|---|---|
| build | `build_manifest(matrix="pairwise", seeds=[0], expand_interventions=profile)` | 496 |
| reviewed omissions | `_apply_gate_blocked_exclusions` | 482 (14 of the 21 entries match this manifest) |
| twin lane | `verify_manifest_twins(mode="bill_verified_only")` | 44 groups, 132 cases, 56 unverified → 426 |
| modality lane | `inventory_selected_modalities(provider=atria, model, target modalities)` | 10 unsupported `rope` cases → 416 |
| gate set | `_order_cases_referenced_first` + env in `REFERENCES` | **189** |

Every intermediate lands on a number a live leg printed: `132 intervention cases, 56 unverified`
is the leg's own `twin preflight` line, `416` is the sidecar's `/ 416`, `189` is its
`Gate checkpointed 189`. Both pairwise profiles are identical here (`reasoning_atria` and
`mercury` give the same four numbers), so this is the campaign's selection, not a paraphrase of it.

Consequences, most important first:

- The wall is 189 rows and 189 rows are banked. Paid work cannot begin unless
  `instance_coverage_complete = all(row["status"] == "passed" for row in gate_rows)`
  (`tools/run_suite.py:872-904`, raised before any credential is built), so the gate is
  **complete and green**, not partial.
- 12 of those 189 rows are the blocked class: `glyph__` with `red_herring=hard` or
  `symptom_mask=hard`. Those are the 12 ids the state artifact's `instance_oracles.json` listed as
  blocked before `4ca1123`, so their passing is the validation of the repair. It is not validation of
  anything else: no `rope` or `moco` code was touched.
- The 21 profile omissions delete a further 9 blocked-class glyph rows (27 in the built manifest, 18
  after exclusions, 12 inside the wall after the twin lane). Those 9 have still never been graded
  post-repair. They stay omitted: reproducing them locally is unfaithful here (a hand-built call to
  `validate_manifest_instances` blocks in 6 s on `FAIL_CODE: empty_patch` because the judge rejects
  the reconstructed `no_op`, and `requirements.txt` ships no torch), and widening a gate without
  evidence is the exact failure `tests/test_gate_failure_diagnostics.py:175-183` exists to catch. Lift
  them when a leg enumerates them and passes, not before.
- Two of my own claims today were wrong in opposite directions and are recorded so nobody repeats
  them: `189 / 189` was quoted from a line that literally reads `189 / ?` (the denominator is absent
  from the progress file once the phase is `episodes`), and the follow-on "482 ≠ 189 ⇒ the campaigns
  are 39% through gating" was an artifact of stopping at the manifest instead of the campaign's own
  three narrowing steps. The sidecar now recovers the denominator from
  `checkpoint.instance_gate.gated_case_count` (falling back to the leg report), so `?` prints only
  when no durable count exists. Legs still pinned to a commit before this one keep printing `?`.

## 2026-10-12 (afternoon): the cadence died with the cron intact, so the legs now re-arm themselves

Both pairwise campaigns went silent while everything that is supposed to restart them looked healthy. Measured at 17:17Z against the last status comments (14:41Z / 14:42Z):

- `Reasoning-Atria pairwise campaign`: run 14 `09:45Z -> 14:42Z completed/failure`, 75 / 416 episodes, `Campaign state: paused`, `Pause reason: max_wall_seconds`.
- `Mercury pairwise campaign`: run 18 `09:46Z -> 14:41Z completed/failure`, 162 / 416 episodes, same pause reason.
- Both workflow files on `main` still carry `schedule: cron: "13,43 * * * *"`, and both workflows still report `state: active`. **No run was created by any workflow in the repository after 09:46Z** - not for these two, not for `Atria covering campaign`, whose last run was 02:39Z. So the trigger definition is fine and the runner simply stopped being handed events; nothing in the repository could see or repair that.
- Ledger state is safe, which is the part worth saying plainly: `run 13` / `run 17` are the zero-minute refused ticks and each lists **no artifact**, so a tick that decides `mode=none` cannot overwrite the lineage state. The rows in 162 / 416 and 75 / 416 are exactly what the legs uploaded.

The fix is not "dispatch it again". `tools/campaign_rearm.py` runs as the last step of both pairwise launchers, after the state upload, and asks the API for the successor run when and only when the leg's own `campaign_report.json` says `status: paused` with a `resumable` pause. Guards, each with a test:

- a leg already `queued`/`in_progress`/`waiting` -> skip (no pile-ups);
- a spin floor: the most recent leg must be older than `--min-interval-seconds` (30 min default), so a leg that dies in four minutes cannot drive the scheduler;
- the run list must be *readable*; unknown "is something running?" is answered by refusing;
- a workflow whose `state` is not `active` is reported rather than raced against;
- every failure path prints a reason and exits 0, so a broken re-arm costs one missed tick instead of reddening a campaign. The cron remains, additive.
- the payload is `resume_previous: true` plus the leg's own `ref`. It never sends `rebase_onto_ref` and never mentions an execution mode, so a re-arm cannot re-pin code or authorize billing; those stay human dispatches.

The launcher gains `permissions.actions: write` for that POST, which is the only privilege change. Tests: `tests/test_campaign_rearm.py` (decision branches, two executed fail-open CLI runs, and static checks over all four launcher copies - last step, `always() && mode != 'none'`, upload precedes it, flags validated against this tool's argparse, and `resume_previous`'s default pinned to `true` because that default is the backstop if the payload is ever rejected).
