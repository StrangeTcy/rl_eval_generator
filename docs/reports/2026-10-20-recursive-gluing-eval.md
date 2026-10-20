# Recursive gluing frontier evaluation — implementation report

Date: 2026-10-20
Branch: `arena/aa22370a-rl-eval-generator`
Commits: `7d3d18e` (implementation) and `f849375` (report) on top of base `bd19804`; the workflow-script fix below lands as a further commit on the same branch.
Remote: pushed to `origin/arena/aa22370a-rl-eval-generator`

Compare: <https://github.com/StrangeTcy/rl_eval_generator/compare/bd19804...arena/aa22370a-rl-eval-generator>

Everything below was executed in this checkout. No provider call was made and no
paid dispatch was run: every number in the "Results" section comes from the
provider-free plan and gate paths.

## 1. What was built

| Path | Role |
| --- | --- |
| `tools/recursive_gluing_study.py` | `plan` / `run` / `report` profile for the study. Builds a filtered manifest and a provider-free budget plan, refuses ceilings that do not fit, forwards `live` to `tools/run_suite.py`, and turns the checkpoint into JSON + CSV + Markdown. |
| `tools/recursive_references.py` | Host-side correct/wrong patch pairs for the exact-instance gate. Eight family members are wired in; the correct patch embeds the environment's own `network.py` oracle, the wrong patch is the environment's naive baseline (or an explicit foil where the baseline is not wrong enough). |
| `tools/instance_oracle_gate.py` | `REFERENCES.update(tools.recursive_references.references())` — no behaviour change for existing environments. |
| `envs/registry.yaml` | The nine recursive environments restored (48 entries total, `yaml.safe_load` verified). |
| `envs/cat_theo/recursive_*/` | Nine environments (config, prompt, solver stub, visible tests, judge, network). Nine judge defects fixed: `torch.load(..., weights_only=True)` where it was `False`, and the deferred `_eval_runner.py` no longer interpolates anything but the judge workdir (the payload is written to `_payload.json` and passed as `argv[1]`), which is what `tools/judge_preflight.py` requires. |
| `docs/workflows/recursive-gluing-eval.yml.example` | The workflow: one `workflow_dispatch`, plan → gate → live → report, host-only credentials, bounded artifacts. |
| `docs/workflows/recursive-gluing-eval.md` | Deployment note (exact destination, permission evidence) and dispatch/rerun instructions. |
| `tests/test_recursive_gluing_study.py` | Sixteen provider-free tests: the ten enumerated properties plus parametrised cases and the manual-copy workflow contract. |
| `docs/audits/2026-10-20-workflow-token-repair.md` | The `.github/workflows/*` token repair this App is not allowed to push (see §6). |

## 2. The diagnostic matrix (scope `diagnostic`, the default)

18 cases = 9 curated cells × 2 conditions. Seeds are fixed in the profile, never
resampled; `seed=1` is the held-out stability repeat of the maximum-depth cell.

| factor | environment | difficulty vector (axis order) | seed |
| --- | --- | --- | --- |
| `baseline_tree_sat` | `recursive_gluing` | `easy,easy,easy,easy` (depth, state, gluing, labels) | 0 |
| `cyclic_sat` | `recursive_gluing` | `medium,medium,medium,easy` | 0 |
| `cyclic_unsat_locally_nonempty` | `recursive_gluing` | `medium,medium,hard,easy` | 0 |
| `opaque_labels` | `recursive_gluing` | `medium,medium,medium,hard` | 0 |
| `opacity_x_unsat` | `recursive_gluing` | `medium,medium,hard,hard` | 0 |
| `nested_tree_opaque` | `recursive_gluing` | `medium,medium,easy,hard` | 0 |
| `max_depth_unsat` | `recursive_gluing` | `hard,hard,hard,hard` | 0 |
| `max_depth_unsat_stability_seed` | `recursive_gluing` | `hard,hard,hard,hard` | 1 |
| `baseline_tree_sat` | `recursive_gluing_discovery` | `easy,easy,easy,easy,easy` (+ `structural_ambiguity`) | 0 |
| `cyclic_sat` | `recursive_gluing_discovery` | `medium,medium,medium,easy,easy` | 0 |
| `cyclic_unsat_locally_nonempty` | `recursive_gluing_discovery` | `medium,medium,hard,easy,easy` | 0 |
| `opaque_labels` | `recursive_gluing_discovery` | `medium,medium,medium,hard,easy` | 0 |
| `decoy_leaf` | `recursive_gluing_discovery` | `medium,medium,medium,easy,hard` | 0 |
| `copy_upward_foil` | `recursive_gluing_discovery` | `medium,medium,hard,easy,hard` | 0 |
| `opacity_x_unsat` | `recursive_gluing_discovery` | `medium,medium,hard,hard,easy` | 0 |
| `max_depth_unsat` | `recursive_gluing_discovery` | `hard,hard,hard,hard,hard` | 0 |
| `max_depth_sat` | `recursive_gluing_discovery` | `hard,medium,medium,hard,easy` | 0 |
| `max_depth_unsat_stability_seed` | `recursive_gluing_discovery` | `hard,hard,hard,hard,hard` | 1 |

Coverage is asserted by test, not by prose: a baseline SAT cell, cyclic SAT in
both conditions, cyclic UNSAT whose local tables stay non-empty in both,
opaque labels, the decoy leaf, the maximum intended depth (3 for the expanded
control, 12 for the compact grammar), a held-out seed, and a strength-2
interaction cell per condition (`opacity_x_unsat`: obstruction × opacity at
depth ≥ 2, the configuration that separates "copy the local table upward" from
reconstructing the composition rule).

Expected budget for the default dispatch (`max_steps=24`, `max_tokens=4096`,
`invalid_retries=2`):

| quantity | value |
| --- | --- |
| cases | 18 |
| worst-case API calls | 1,296 |
| worst-case output tokens | 5,308,416 |
| estimated wall | 14,400 s (`18 × 600 + 3600` gate reserve) |
| declared ceilings | 2,000 calls / 8,000,000 tokens / 14,400 s |

The plan refuses a dispatch whose ceiling is below the worst case, and refuses a
wall ceiling above 21,000 s (a hosted runner must be able to upload its
checkpoint instead of being killed).

## 3. Results (all provider-free)

| Command | Result |
| --- | --- |
| `python tools/recursive_gluing_study.py plan --scope diagnostic` | exit 0, 18 cases, budget above, `within_limits: true` |
| `... run --execution-mode gates_only` (diagnostic) | exit 0, **18/18 instances passed**, `provider_calls: 0`, `provider_free_validation_complete: true` |
| `... plan --scope family --matrix pairwise` | exit 0, 76 cases over 8 members, `recursive_holonomy_gluing` excluded, 5,472 calls / 22,413,312 tokens / 49,200 s |
| `... run --execution-mode gates_only` (family) | exit 0, **76/76 instances passed**, `provider_calls: 0` |
| `... plan --scope family --shard-count 4 --shard-index 0..3` | 19 cases / 15,000 s each; union = the 76 full ids, disjoint, deterministic |
| `python tools/judge_preflight.py` (via `generate_env.py`) | all nine recursive judges pass; one deferred script each |
| `python -m pytest tests/test_recursive_gluing_study.py -q` | **16 passed** (includes a `bash -n` parse of every workflow shell step) |
| `python -m pytest tests/test_recursive_*.py -q` | **171 passed** |

Each gate row grades the exact instance the episode would run, four ways: an
empty patch (must fail `patch_invalid`, score 0), a comparable wrong patch (must
fail the named held-out check, below threshold), a transcription trap where the
environment has one, and the reference (must score 1.0). Representative
separation on hard vectors: `recursive_gluing` wrong 0.167 (`obstructed_cycle`),
`recursive_gluing_discovery` wrong 0.104 (`assembled_unsat`),
`recursive_maze_gluing` 0.119, `recursive_distributed_gluing` 0.0,
`recursive_epistemic_gluing` 0.093, `recursive_coarse_graining` 0.119,
`recursive_compiler_bootstrap` 0.729, `recursive_error_correcting_codes` 0.119.

Report path exercised on the gate-only checkpoint:
`report` wrote `results.json`, `results.csv` (76 rows, 23 columns) and
`summary.md`; every case is `missing_result` (correct for a gate-only run),
`cross_condition_aggregation: none`, `usage.provider_calls: 0`.

`shared/{judge_lib,patch_validator,source_validator,submit}.py` still fail a bare
`compile()` — and that is correct: they are generation templates carrying
`%%PATCHABLE_FILES%%` placeholders that `generate_env.py` substitutes. The
generated judges compile, and the generated workspaces run (the gate exercises
them 76 × 4 times).

## 4. Deployment (manual copy, one step)

The workflow is **not** deployed. `docs/workflows/recursive-gluing-eval.yml.example`
must be copied to `.github/workflows/recursive-gluing-eval.yml` once, by a token
that may write workflow files, then merged to the default branch:

```bash
cp docs/workflows/recursive-gluing-eval.yml.example .github/workflows/recursive-gluing-eval.yml
git add .github/workflows/recursive-gluing-eval.yml
git commit -m "Add the recursive gluing frontier evaluation workflow"
```

It becomes dispatchable only after that commit is on the default branch. The
workflow takes `scope`, `execution_mode` (`plan_only` default, `live`), `provider`,
exact `model`, `matrix`, `seeds`, the two ceilings plus a wall ceiling,
`max_steps`, `max_tokens`, the wire API, optional reasoning effort / base URL, and
`shard_index`/`shard_count`. It has no `schedule`, no `repository_dispatch`, no
self-re-dispatch and no `cancel-in-progress`, and it holds `contents: read` only.

## 5. Dispatching and downloading

```bash
gh workflow run recursive-gluing-eval.yml \
  -f scope=diagnostic -f execution_mode=plan_only \
  -f provider=atria -f model=atria-dawn-preview -f wire_api=responses

gh run download <run-id> -n recursive-gluing-plan-diagnostic-<run-id>   # plan.json / plan.md / study_manifest.json

gh workflow run recursive-gluing-eval.yml \
  -f scope=diagnostic -f execution_mode=live \
  -f provider=atria -f model=atria-dawn-preview -f wire_api=responses \
  -f max_api_calls=2000 -f max_tokens_total=8000000 -f max_wall_seconds=14400

gh run download <run-id> -n recursive-gluing-results-diagnostic-atria-shard0-<run-id>
```

The results artifact contains the checkpoint, `instance_oracles.json`,
`oracle_preflight.json`, per-case `final.json` / `result_record.json` /
`model_responses.jsonl` / `submission.patch`, and `report/{results.json,results.csv,summary.md}`.
Artifacts are bounded (14 days for the plan, 30 days for the results).

Whole-family rerun (four shards, one dispatch each):

```bash
for i in 0 1 2 3; do
  gh workflow run recursive-gluing-eval.yml \
    -f scope=family -f matrix=pairwise -f execution_mode=live \
    -f provider=atria -f model=atria-dawn-preview -f wire_api=responses \
    -f shard_index=$i -f shard_count=4 \
    -f max_api_calls=2000 -f max_tokens_total=8000000 -f max_wall_seconds=14400
done
```

`report --run-out <dir>` accepts one entry per shard, merges them, records
`shards`, and reports a case graded twice instead of averaging it.

## 6. Permission evidence

A push that touched `.github/workflows/**` was attempted from this branch and
rejected:

```
! [remote rejected] HEAD -> arena/aa22370a-rl-eval-generator
  (refusing to allow a GitHub App to create or update workflow
   `.github/workflows/mercury-pairwise-campaign.yml` without `workflows` permission)
```

The branch itself then pushed cleanly with the workflow changes excluded. This is
why (a) the workflow ships as a `.yml.example`, and (b) the repair of the
corrupted tokens in the two pairwise campaign workflows (present at the base
commit) is carried as a patch in `docs/audits/2026-10-20-workflow-token-repair.md`
rather than applied.

## 7. Coverage, exclusions, limitations

* **Excluded from live scored evaluation: `recursive_holonomy_gluing`.** Its pass
  threshold is 0.85 and a locally consistent but globally wrong certificate still
  scores 6/7 = 0.857 on seven of its ten pairwise vectors, so those vectors have
  no discriminating negative control and the gate refuses them. Ten cases are
  dropped, with this reason, in every plan and report. Tuning a "more wrong" arm
  for the gate would certify the reference file rather than the environment.
* **`representation` is pinned to `revealed`** for `recursive_coarse_graining`,
  `recursive_compiler_bootstrap` and `recursive_error_correcting_codes` (and would
  be needed for holonomy). At `representation=inferred` the judge's own reference
  certificate cannot be replayed from the public instance, so those columns have
  no behavioural reference. The pin is recorded per case (`study.pinned_levels`)
  and per manifest (`study.axis_pins`, with the reason). No column is guessed at.
* **No compile-only path.** Uncertified cases are dropped, never relabelled as
  validated; the report has a `compile_only_unvalidated` category for guarded
  environments and the study emits none.
* **No pooling.** The report has no overall score: `cross_condition_aggregation`
  is `"none"` and counts are per condition, per environment and per factor.
  Expanded-control and compact-discovery results are never combined.
* The gate's correct patch embeds the environment's own oracle. The gate proves
  judge separation on the exact instance; it is not an independent second solver.
* The gate runs `sandbox="local"`; Docker isolation is a property of the live path.
* The wall estimate is a ceiling (`cases × 600 s + 3600 s`), not a forecast.

## 8. Pre-existing failures in this branch (not caused by this change)

`tests/test_pairwise_matrix.py` has five failures (campaign profiles priced
against their own matrix, e.g. `reasoning_atria_covering_campaign` bound 71,286
vs ceiling 56,166). They reproduce with `envs/registry.yaml` restored from
`bd19804`, i.e. they are on the base commit and unrelated to the study. They are
left alone: the campaign profiles are different experiments and their ceilings
are not this dispatch's to raise.

## 9. Outstanding

1. Copy the workflow to `.github/workflows/recursive-gluing-eval.yml` (manual, §4).
2. Apply `docs/audits/2026-10-20-workflow-token-repair.md` with a token that may
   write workflows.
3. Dispatch `plan_only`, read the plan, then dispatch `live` once a model id and
   provider credential are chosen.
