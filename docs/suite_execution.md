# Safe suite execution

The suite inventory is declarative and provider-free. Generate it after the
compatible environment integration and keep the resulting revision pinned in
the manifest:

```bash
python tools/suite_inventory.py \
  --out suite_manifest.json \
  --matrix representative \
  --seeds 0 \
  --compare-ref origin/arena/01a0be02-rl-eval-generator
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

## Zero-call oracle gate

Before a live sweep, `tools/run_suite.py` runs
`tools/oracle_preflight.py` on the manifest. This gate makes **zero API calls**.
It generates one representative case per environment, compiles the generated
Python, checks judge imports/globals, and renders and checks deferred evaluation
scripts (which plain compilation of `judge.py` cannot inspect). It also runs any
configured deterministic reference self-test and applies a declared
`oracle.known_good_patch` only as a clean-application check. These static checks
do not prove grading correctness. The report is written to
`oracle_preflight.json`; a failure stops the sweep before credentials are
resolved for a provider request. The report now marks compile-only cases
`reference_self_test: not_configured` and lists them in `unverified_environments`
instead of calling their absent self-test "passed." A live suite or pilot with
incomplete behavioral reference coverage **blocks before any provider call**.
The explicit `--allow-compile-only-oracles` override records this risk in
`oracle_preflight.json`; use it only after independently exercising the selected
judges against known-good and failing submissions. It does not create evidence.

With PyTorch installed, `pytest tests/test_judge_behavior.py` runs real offline
known-good submissions for state-carry, RoPE, and MoCo. Without PyTorch those
tests are skipped; normal `pytest` and judge compilation are not equivalent to
a behavioral oracle for every environment, including glyph.

The `epistemic_games` environment uses the public-only Bayes oracle self-test.
That oracle is a consistency check for the configured reference behavior, not a
claim about a model's reasoning process.

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
