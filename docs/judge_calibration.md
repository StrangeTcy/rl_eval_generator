# Judge calibration log

One entry per judge/gate bug: symptom, how it was found (audit vs. after the
pilot), root cause, whether it could have changed any recorded score, the fix
commit, and its regression test. The "could it have changed a score" column is
the one readers should check first: fail-closed bugs (wrong things blocked)
and bugs in never-certified environments cannot have altered a recorded score;
false-pass bugs in certified environments can.

Score-affecting context: the only paid runs so far are the Atria and NVIDIA
first-five pilots (`experiments/atria_first5.yaml`, `experiments/nim_first5.yaml`),
both on `regex_state_machine`, `epistemic_games`, `categorical_lenses`,
`rd_state_carry`, and `glyph` at their pinned vectors. Historic pilot patches
and trajectories were never available locally, so nothing has been re-scored.

## Second validation pass — 2026-09-26, branch `arena/01a0dc92-rl-eval-generator`

Scope: pinned-torch full suite with zero torch skips; opt-in slow oracles;
exact-instance oracle wiring audit; no-op / plausible-wrong / transcription
false-positive checks; behavioural validation of all six weird_machine judges;
pinned CPU-torch CI job. No provider calls were made.

### 1. Spreadsheet gate reference emitted its recurrence as a plain string

- **Symptom:** the gate's *reference* patch for `spreadsheet_dataflow` graded
  as FAIL (`basic_eval: false`, `randomized_invariance: false`), so every
  spreadsheet case would have been blocked as `reference_did_not_grade_as_expected`.
- **How it was found:** audit — by the new multi-seed weird_machine quadruple
  sweep (item 5) *before* any commit; not after a pilot.
- **Root cause:** the gate's generated `build_dp_formulas` wrote
  `formulas[f"B{i}"] = "=A{i}+MIN(B{i-1},B{i-2})"` — the recurrence was
  interpolated into the generated source as a plain string literal, so the
  `{i}` placeholders never evaluated and every B-cell formula was the literal
  text `=A{i}+MIN(B{i-1},B{i-2})`. The generated line needed an `f` prefix.
- **Could it have changed a recorded score:** No. It is strictly fail-closed
  (the reference itself fails → gate blocks the run), spreadsheet_dataflow was
  previously not even in the reference registry, and it never reached a commit
  or a paid gate decision.
- **Fix commit:** `7c67aaf`
- **Regression test:** `tests/test_weird_machine_oracles.py` — the
  spreadsheet quadruple (reference must PASS) at seeds 0–2 easy and hard.

### 2. Template transcription patch was a syntax error

- **Symptom:** the new `template_interpreter` transcription variant graded as
  `source_invalid` (a SyntaxError in the submitted file) instead of reaching
  the judge's behavioural checks, so it could not demonstrate anything about
  hard-coding detection.
- **How it was found:** audit — by the same sweep, before any commit.
- **Root cause:** the transcription source embedded the Jinja2 template in a
  single-quoted Python string spanning multiple lines; Python string literals
  cannot contain raw newlines. Collapsed to a single line.
- **Could it have changed a recorded score:** No — new, uncommitted code;
  also fail-closed in effect (the variant is rejected as an invalid source,
  never accepted).
- **Fix commit:** `7c67aaf`
- **Regression test:** `tests/test_weird_machine_oracles.py` — the
  template_interpreter transcription must be `patch_valid` with
  `template_syntax: true` (a working hard-code of the visible tests) and still
  FAIL `randomized_rendering`.

### 3. batchnorm_ema easy/medium vectors award full credit to patches that fix nothing — OPEN

- **Symptom:** a plausible-but-wrong patch — an "off-by-one fix" of the
  accumulation boundary that is an equivalent reformulation, plus a classifier
  re-init, leaving BN momentum unscaled — scored **1.0 / PASS** at both
  `easy,easy,easy,easy,easy` and `medium,medium,medium,medium,medium` seed 0
  (`raw_accuracy: 1.0`, `running_stats_sane: true`, `eval_mode_consistent:
  true`, `anti_gaming_passed: true`; ~1119 s and ~1103 s CPU respectively).
  The env's own easy visible test (`assert bn.momentum != 0.1`) rejects that
  patch while the judge accepts it.
- **How it was found:** audit — this pass's false-positive check (item 4).
  Not after a pilot: batchnorm_ema has never been in a pilot.
- **Root cause:** at easy/medium the injected bug (unscaled BN momentum under
  gradient accumulation, effective momentum ≈ 0.34 at ACCUM_STEPS=4) is
  behaviourally inert: the training loader shuffles i.i.d. batches over
  template data, so even a fast-EMA running statistic stays accurate enough
  to classify the held-out set perfectly. No route-agnostic post-hoc probe on
  the trained model can distinguish it, because the trained model genuinely
  works. The hard vector is protected by a *different* mechanism — the ghost
  `train()` override — which `eval_mode_consistent` catches (pinned by the
  existing probe test in `tests/test_batchnorm_judge.py`).
- **Could it have changed a recorded score:** No. batchnorm_ema has no gate
  reference, so every paid run including it is blocked (`reference_not_configured`
  → whole manifest blocked), and neither pilot contained it. The false
  positive is reachable only in offline/local scoring.
- **Fix commit:** none yet — the fix is a calibration decision (see the
  decision list below), not a mechanical correction.
- **Regression test:** `tests/test_batchnorm_judge.py::test_noop_submission_fails_closed_under_real_judge`
  pins the no-op fail-closed behaviour; the wrong-patch PASS is documented in
  that test's docstring and here, deliberately *not* asserted in CI until the
  calibration decision is made.

## Previously recorded — first pass, commit `e4a0d76`

Recorded here for completeness; details and evidence live in
[docs/suite_execution.md](suite_execution.md) and the commit itself.

- **Exact-instance oracles now fail closed.** Previously an unconfigured or
  failing reference could be treated as compile-only "verified"; now missing
  references, wrong grades, timeouts, unknown failure modes, and pinned-config
  drift block all paid calls, and the direct episode byte-compares the agent's
  actual reset against the oracle-graded instance fingerprint. Found by audit
  before any paid sweep.
- **`score_from_accuracy` anti-gaming gates became load-bearing.** BatchNorm
  judge checks (`running_stats_sane`, `eval_mode_consistent`) were previously
  diagnostics only; a model could PASS while updating BatchNorm statistics on
  every eval batch. Found by audit.
- **100-class batchnorm data degeneracy.** With the 24-template/100-label
  distribution, the hard vector was unclassifiable from public training data
  (~30% nearest-template oracle vs a 75% threshold); the label→column formula
  now encodes the higher class group (100 distinguishable templates). Found by
  audit.
- **Vector-specific reference fragility.** A reference that passes one vector
  can fail another (the state-carry false negative appeared at one exact seed
  and difficulty); the gate therefore grades the exact selected vector/seed —
  confirmed in this pass by code audit of `arena/episode.py` (oracle runs on
  the episode's exact vector before credentials are resolved; actual reset is
  byte-compared) and by `tools/run_suite.py` / both first-experiment tools
  (manifest-level gating before any paid call).

## Decision list (found, not fixed — awaiting a call)

1. **Pilot judge PyTorch version unrecorded; judge Docker images were
   unpinned.** `shared/Dockerfile.judge` installed unpinned
   `torch torchvision`, so judge images were not reproducible across builds
   and the pilots' actual judge-side torch version is unrecoverable.
   RESOLVED for future builds: `shared/Dockerfile.judge` now pins
   `torch==2.5.1 torchvision==0.20.1` (commit `b0a0004`), matching the
   documented validation baseline and the behavioural CI example. Remaining
   operator step: print and record the in-container version once per built
   image before a paid run.
2. **batchnorm_ema calibration (entry 3 above).** Options: make the EMA
   staleness behaviourally visible (e.g. class-correlated batches), raise
   ACCUM_STEPS so unscaled momentum collapses eval accuracy, restrict
   scoring-eligible vectors to hard, or accept and document easy/medium as
   non-discriminating. Note the easy visible test (`momentum != 0.1`) is
   route-specific and contradicts the judge's stated route-agnostic philosophy
   (a GroupNorm swap is meant to be a valid fix but fails that visible test).
3. **batchnorm_ema has no gate reference**, so paid runs including it stay
   blocked. Adding one is a decision and depends on 2.
4. **Root-level `test_cat_theo.py` / `test_weird_machine.py`** are manual
   generation-smoke scripts (not pytest tests; `testpaths` excludes them).
   They pass as of this pass (all 23 environments generate and compile with
   zero unresolved placeholders) but are wired into nothing; wire them into
   CI or delete them.
5. **Campaign runs paid cases under compile-only judges for the 22
   environments without a behavioral reference** (2026-09-26, explicit
   operator choice for the covering campaign). This relaxes the repo's
   standing invariant that an unconfigured reference blocks paid calls even
   with `--allow-compile-only-oracles`. The relaxation is scoped: opt-in per
   campaign profile (`unreferenced_compile_only: true`), every affected
   result row is labeled `judge_guarantee=compile_only`, the report carries
   a not-a-validated-verdict disclaimer, and the pilot path plus default
   scheduler behavior still refuse such cases. Whether compile-only rows
   should ever count as model results — rather than infrastructure
   telemetry — remains open.
6. **Campaign resumes carry the exact-instance gate pass** (2026-09-26).
   Re-running CPU-hours of reference validation on every resume made the
   resilient campaign impractical, so a resume accepts the checkpoint's
   recorded gate pass only when the gated case list and the deployed code
   SHA match exactly; any drift re-runs the full gate. This is the
   previously-deferred "gate caching" decision, now constrained to
   metadata-keyed carry-over within one campaign's checkpoint chain: it
   cannot leak across manifests, code versions, or independent runs.
7. **Gate-phase cost exceeds the 6-hour GitHub job cap** (2026-09-26,
   sharpened 2026-09-27). Runner-side pilot data: one glyph gate case cost
   ~552 s (reference) + ~313 s (plausible-wrong) ≈ 865 s. The covering
   matrix has 13 glyph and 13 moco cases; at the easy-equivalent rate,
   glyph alone is ~3.1 h and glyph+moco ~6.2 h — the whole usable job
   budget — before the other 53 referenced cases, and harder vectors
   train longer. The first dispatch therefore cannot complete the full
   gate inside one 350-minute job, and restart-once cannot recover it:
   the gate record is written only when the entire gate completes, so a
   mid-gate death loses everything. Correction to the earlier hand-split
   sketch: the designed gate carry is all-or-nothing (same gated-manifest
   SHA + context SHA skips the whole gate; anything else re-runs it), so a
   split job that gates only glyph+moco cannot carry its pass into the
   campaign — the split requires per-case gate accumulation and
   incremental gate checkpointing first. Until that exists, the options
   are: run the gate on a dedicated long-running machine, or accept burning
   ~6 h jobs that die mid-gate.
   RESOLVED for the campaign (2026-09-27): the gate now accumulates per
   case — each completed row is checkpointed atomically to
   `instance_oracles_partial.json` and carried forward on resume under the
   same case-content hash and code context, so dispatches killed mid-gate
   resume gating only the missing cases. The exact-instance guarantee is
   unchanged: no paid call happens until every referenced case has a
   passed row in the merged report.
8. **A single gate case that cannot fit one job budget would spin the
   supervisor forever** (2026-09-27, not built — theoretical until timing
   says otherwise). The forward-progress floor ("bank one fresh row
   before GateWallExceeded may raise") makes the multi-job gate converge
   whenever every case fits the phase-1 wall budget. If one case's
   validation exceeds it (e.g. a hardest-difficulty Glyph vector on a
   slow runner), the job runs to the step timeout, banks nothing, and
   the cron retries the same case forever with zero progress. Runner-side
   pilot data (one easy glyph case ~14.4 min) leaves orders of magnitude
   before the ~5.2 h gate wall, so this is currently theoretical; the
   sandbox smoke's first glyph row (in progress >21 min on 2 cores) and
   the first dispatch will tell. If it becomes live, the fix is: when the
   partial file shows the same first-unfinished case across N
   consecutive dispatches with no new rows, pause non-resumably with
   pause_reason gate_case_exceeds_job_budget and the case ID, so a human
   decides whether to split, defer, or drop that case. Recorded here
   instead of built, per review.

## Validation environments for this pass

- torch 2.14.0+cu130, torchvision 0.29.0, numpy 2.4.6, jinja2 3.1.6,
  pytest 9.1.1, PyYAML (Python 3.11.2, 2 CPU cores): full suite
  229 passed / 1 opt-in skip; slow Glyph oracle 1 passed in 8:30.
- torch 2.5.1+cu124 / torchvision 0.20.1 (the documented baseline; the CI
  behavioural pin), same host otherwise: full suite with
  `RUN_SLOW_JUDGE_ORACLES=1` — **255 passed, 0 skipped**, including the slow
  Glyph oracle, all 24 weird_machine quadruples, and the batchnorm no-op
  fail-closed check.
- torch 2.5.1+cu124 / torchvision 0.20.1 / numpy 2.1.2 (Python 3.11.2,
  2 CPU cores), 2026-09-26 campaign pass: full suite on the campaign code
  — **251 passed, 1 opt-in skip** (the opt-in slow Glyph oracle stays a
  separate, unexecuted check; the live gate smoke over the covering matrix
  exercises the same oracle family but is not a pytest result). Caveat:
  this is the CUDA 12.4 wheel running on CPU, not the workflow's
  `+cpu` wheel from the PyTorch CPU index — same upstream version, so
  numerics are expected to match, but the exact-runtime record remains the
  pinned `+cpu` stack on the GitHub runner. This is the first full-torch
  execution of the campaign/scheduler tests; they also pass torch-less
  (stub-based, 28-test local run).
