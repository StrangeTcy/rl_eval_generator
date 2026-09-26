# Safe suite execution

The suite inventory is declarative and provider-free. Generate it after the
compatible environment integration and keep the resulting revision pinned in
the manifest:

```bash
python tools/suite_inventory.py \
  --out suite_manifest.json \
  --matrix representative \
  --seeds 0 \
  --compare-ref origin/main
```

The manifest records the checkout revision, a deterministic config inventory
digest, and for every requested Git ref both `missing_from_checkout` and
`only_in_checkout`. A missing config makes the manifest ineligible for the
scheduler; checkout-only configs are recorded so an additional branch is not
silently described as covered.

## Matrix and token guard

`representative` is the runnable default. It selects one declared level per
axis. `all` expands the Cartesian product and is not an implicit sweep. A live
all-matrix scheduler run must either be a `--dry-run` or provide an explicit
estimated output-token ceiling:

```bash
# Planning only: no credentials or provider request is read.
python tools/run_suite.py --manifest suite_all.json --dry-run \
  --provider custom --model provider/pinned --api-key-env UNUSED

# Live execution requires an account-approved key and an explicit ceiling.
python tools/run_suite.py --manifest suite_all.json \
  --provider groq --model provider/model-version \
  --api-key-env GROQ_API_KEY --max-tokens-total 50000 \
  --max-cases 2 --sandbox docker
```

The estimate is `cases × max_steps × (1 + invalid_retries) × max_tokens`.
Lower `--max-cases`, `--max-steps`, and `--max-tokens` before raising the
ceiling. There is no automatic paid fallback or top-up.

## Pre-provider oracle gate (zero provider calls)

There are two separate checks. `tools/oracle_preflight.py` compiles one rendered
case per environment and inspects generated/deferred judge scripts. The
`public_bayes_oracle` self-test covers its own examples, **not** every manifest
case. Its legacy `model_sweep_allowed` field means *static preparation*, not
judge accuracy. A patch applying cleanly is not a behavioral PASS.

**Live** suite and both first-five pilots now also call
`tools/instance_oracle_gate.py` **before credentials or even a paid
compatibility call**. It generates each selected `(environment, difficulty,
seed)` once and, through the real local patch-validator/judge path on that
same generated instance, submits three patches separately:

1. Empty no-op must score zero as `patch_invalid`.
2. A *valid* plausible-wrong patch must fail a named behavioral check and
   receive **less than 1.0**. Merely rejecting an invalid diff does not count.
3. A reference repair must receive **1.0/PASS** with `failure_mode: pass`.

The gate records the generated-instance SHA-256, patch SHA-256s, verdicts,
behavioral checks, and timing in `instance_oracles.json`, without exposing a
reference patch in the agent workspace. Before the first model action, the
direct episode also compares the *actual* agent reset's pristine workspace and
judge bytes against that reference-graded fingerprint; a regenerated instance
that differs despite matching vector/seed is an infrastructure error, not a
model score. Any missing reference, incorrect score, timeout, unknown failure
mode, or pinned config drift blocks the call.
The old `--allow-compile-only-oracles` flag cannot bypass this behavioral gate.
Direct `arena.py run` episodes apply it too and record their own report under
`runs/_instance_oracles/`. The suite also checks its selected cases independently;
this redundancy costs local CPU time but not API tokens. A `--dry-run` remains
a budget plan and **does not** execute behavioral oracles.

The gate currently has concrete references for `rd_state_carry`, `rope`,
`moco`, `glyph`, `epistemic_games`, `categorical_lenses`,
`regex_state_machine`, `sql_fixed_point`, and `css_state_machine`. Other
registered environments have **no configured reference** and will block a
live sweep that includes them; don't call them verified. A reference built for
one vector can fail a different vector, so the gate grades the exact selected
vector/seed, not an easier proxy. On the local CPU, Glyph takes about nine
minutes for all three variants. None of these host-side judge checks proves
Docker runtime isolation; the separate CI Docker step builds but does not run
judge containers.

To inspect specific vectors without any provider credential or request:

```bash
python tools/instance_oracle_gate.py \
  --case regex_state_machine:easy,easy:0 \
  --case regex_state_machine:hard,hard:2 \
  --case css_state_machine:hard,hard:1 \
  --out runs/weird_oracles.json

# Slow Glyph test (CPU; matching PyTorch + Torchvision required):
python tools/instance_oracle_gate.py \
  --case glyph:easy,easy,easy,easy,easy,easy:0 \
  --include-slow --out runs/glyph_oracles.json
```

### What was actually executed locally

With PyTorch 2.5.1 and Torchvision 0.20.1 installed locally, no provider calls:

- The exact pilot vectors for regex, epistemic games (bare table), categorical
  lenses, state-carry, and Glyph at seed 0 each passed the three-variant gate.
  Separate MoCo and RoPE easy/seed-0 triples also passed; the plausible-wrong
  scores were **0.95** and **0.8**, respectively, not full credit. State-carry's
  wrong patch scored **0.6**, reference **1.0**. MoCo's wrong patch still has
  `raw_accuracy: 1.0` (downstream k-NN metric), but the failed temperature
  check caps its **final** score below 1.0. Do not treat raw k-NN accuracy as
  proof that its temperature bug was fixed.
- Regex, SQL, and CSS each passed easy and hard at seeds 0, 1, and 2: **18
  exact generated instances**, each with no-op/wrong/reference grading. This
  covers only these three weird-machine environments and these vectors, not
  every weird-machine task or all axis combinations.
- The opt-in Glyph reference needed training to pass at one vector/seed; it
  does not explain why the historical pilot sent an empty submission. The
  pilot's saved patches/trajectories are not present locally (remote artifact
  downloads failed), so **no historical patch has been re-scored** and no
  trajectory probe-path inspection has been performed. Pasted plaintext
  `submission.patch` files, the pinned pilot manifest/commit, and a targeted
  trace excerpt are needed to audit those historical claims; ZIP uploads are
  not required.

These are provider-free **local** tests. CI's `requirements.txt` does not install
PyTorch/Torchvision: tests using `pytest.importorskip("torch")` or
`pytest.importorskip("torchvision")` are skipped, and the opt-in slow Glyph
behavioral test is skipped unless `RUN_SLOW_JUDGE_ORACLES=1`. Check the skip
count, not just the green badge. CI does run static/rendered-judge checks and
Docker **build** smoke, not a behavioral PyTorch or Docker-executed judge suite.

A local PASS cannot retroactively repair a judge failure in a paid trajectory.
Infrastructure failures (`judge_runtime_error`, `unknown`, HTTP 502, Docker
errors) are unscored; keep raw artifacts for attribution rather than assigning
a zero model-ability score.

## Floor-effect stop

For non-reasoning runs, the scheduler defaults to stopping after three
consecutive scored cases with score exactly zero. It records `floor_effect:
true` in the checkpoint, coverage report, and triggering result. Configure it
with `--floor-effect-after N`, or use `--floor-effect-after 0` to disable it.
Passing `--reasoning-effort low|medium|high` marks the run as a reasoning
resource protocol and disables this non-reasoning floor-effect detector; it
does not infer an internal recurrent architecture.

Provider execution remains opt-in. A failed quota, entitlement, model, or
preflight check pauses or stops cleanly instead of trying a paid service.

## GitHub Actions workflow template

`docs/workflows/evaluate-suite.yml.example` is the reviewed manual-workflow
template. To activate it, copy it to `.github/workflows/evaluate-suite.yml`
using an authorized GitHub account with Workflows write permission. Store only
an account-approved CI secret such as `SUITE_API_KEY` in GitHub Actions; do not
upload a personal `secret_key.json`. A `workflow_dispatch` workflow must exist
on the default branch before it can be triggered from the Actions UI.
