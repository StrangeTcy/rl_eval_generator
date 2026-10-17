# Four recursive-gluing applications — evaluation-readiness audit

Date: 2026-10-17.
Branch: `arena/1ddc930c-rl-eval-generator`.
This correction sits on `b961ba6` (hardening) and records what the runner can
actually select, plus full rendered-workspace leakage coverage.

This pass does not add environments. It does not modify maze / distributed /
epistemic / v0 / discovery files.

Passing the tests below is **(1) generator/oracle correctness** and
**(2) shortcut resistance**. It is **not (3) model performance**. The
reference solver composing maps / running interpreters / enumerating
\(\mathbb F_5\) / summing integer tables is not evidence that a language
model does structural reasoning. Unit tests are not benchmark validity.

## 1. Model-facing path

Two distinct surfaces:

| Surface | What it is | What the tests cover |
|---|---|---|
| Public payload | `public_instance` JSON the judge writes into `solve` | Every generator regime × representation, including the non-selectable `flat` branch |
| Rendered workspace | substituted `agent/workspace/{prompt.md,solver.py,visible_tests.py}` | Every **runner-selectable** regime × representation (3×2 per env) |

`generate_env.py --difficulty` only accepts config level names (`easy` /
`medium` / `hard`). Suite inventory (`representative` / `covering` / `all`)
expands those same names. `generation.json` is at the generated-tree root,
not under `agent/workspace`, and is not copied by `shared/Dockerfile.agent`.

Secret fields that must not enter the payload: `meta`, `composite`,
`expect_fixed`, and (when `representation=inferred`) `maps` / `expanded` /
`encodings` / `perms` / `label_perm` / recode `perm` on compiler stages.

The configured `REGIME` / `REPRESENTATION` strings are substituted into
`judge/judge.py` only. Agent files must not contain `recursive_composition`
or `REGIME =`.

## 2. Concern ledger

### Fixed

| Concern | What changed |
|---|---|
| Workspace leakage tested only at all-easy | `test_agent_workspace_has_no_theory_leaks` now generates every selectable regime × representation (24 trees). Judge substitution is checked so the combo actually applied. |
| Audit treated A/B/C/D as if `flat` were a runner condition | Config levels remain `direct` / `recursive` / `recursive_composition`. Tests now prove `flat` is rejected by `--difficulty` and absent from inventory vectors. |
| Config copy listed `direct/flat` as if both were levels | Axis descriptions name only selectable levels. |

Earlier hardening (depth honesty, payload stripping, grammar sampling, coarse
2-spin toy) is unchanged.

### Verified non-issue

| Concern | Evidence |
|---|---|
| `meta` / SAT labels in the candidate payload | Absent from `public_instance` for all generator regimes (including `flat`) and both representations. |
| Theory tokens / selected regime in the agent workspace | All 24 selectable renderings: no sheaf / holonomy / Čech / cohomology / monodromy / gluing / `recursive_composition` / `fixed point`; no unresolved `%%...%%`; workspace file set is exactly prompt, solver, visible_tests. |
| Oracle budget exhaustion treated as unsat | Existing tests still raise `OracleBudgetExceeded`. |
| Shortcut baselines solving D-class | Local-only / trust-the-claim / first-region remain SAT/`equivalent=True`/`fixed=True` on REC_COMP; reference is the opposite. |
| Boolean fields accepted as truthy strings | Existing `type(value) is bool` checks still pass. |

### Unresolved (documented, not claimed away)

| Concern | What it can and cannot establish |
|---|---|
| Directory `recursive_holonomy_gluing` contains `holonomy` | Host/registry name. Not present in the Docker agent workspace. |
| Codes public field `glues` | Schema identifier. Prompt describes overlap constraints. |
| Generator `flat` vs selectable `direct` | Holonomy/compiler/codes: SAT-identical to `direct`. Coarse: one all-ones region (not fixed) vs projector (fixed). **Not selectable.** Do not score a nesting-versus-flat contrast. |
| `recursive` vs `recursive_composition` | Same recursive shape, different polarity (see §3). This is a polarity contrast, not an isolated “more nesting” contrast. |
| `direct` vs `recursive` | Changes structure **and** keeps SAT/`fixed`/`equivalent` true. Cannot attribute a model miss to polarity. |
| Codes inferred coordinate perm | `H=[1 1]` is symmetric. Weak presentation axis. |
| Coarse inferred `label_perm` | A 1-bit swap of `{0,1}`. |
| Compiler depth cap | Grammar height saturates at 2. Requested 3 records 2. |
| Coarse `direct` vs the depth axis | Requested depth 3 still builds one region and records 1. |
| Explicit expansion | Holonomy grade item, not a config level. |
| Model performance | Unmeasured. See §5. |

## 3. Selectable regimes versus generator branches

`easy` / `medium` / `hard` on each regime axis substitute `direct` /
`recursive` / `recursive_composition`. That is the experiment runner’s
choice set. `FLAT = "flat"` in `network.py` is a **tested generator branch**,
not a supported configuration.

### Holonomy (`cycle_regime`)

| Kind | Name | Built structure (depth \(d\)) | Oracle | Contrast |
|---|---|---|---|---|
| selectable | `direct` | identity cycle, \(d\) leaf applications, `root=leaf` | SAT | — |
| selectable | `recursive` | \(d\) leaf applications plus extra SAT factor; `root=node` if \(d\ge 2\) | SAT | vs `direct`: extra factor **and** nesting. Same polarity. **Confounded structure contrast.** |
| selectable | `recursive_composition` | same shape as `recursive`, extra factor has no returning state | unsat | vs `recursive`: same cycle shape, different extra map. Polarity contrast on matched shape. |
| generator only | `flat` | identical to `direct` | SAT | Not in config. Not in inventory. |

### Compiler (`bootstrap_regime`)

| Kind | Name | Built structure | Oracle (`equivalent`) | Contrast |
|---|---|---|---|---|
| selectable | `direct` | one compile stage | True | — |
| selectable | `recursive` | compile + recode; claimed decoder is the true inverse | True | vs `direct`: 1 stage vs 2. Same polarity. **Confounded.** |
| selectable | `recursive_composition` | same two stages as `recursive`; claimed decoder is wrong | False | vs `recursive`: same path, different claim. Polarity contrast on matched structure. |
| generator only | `flat` | identical to `direct` | True | Not selectable. |

Program `depth` is grammar height capped at 2, not stage count.

### Codes (`code_regime`)

| Kind | Name | Built structure (depth \(d\)) | Oracle | Contrast |
|---|---|---|---|---|
| selectable | `direct` | \(d\) independent length-2 blocks, no overlaps, SAT parent | SAT | — |
| selectable | `recursive` | \(d\) blocks, cycle overlaps, parent rhs \(=0\) | SAT | vs `direct`: overlaps added, polarity unchanged. **Confounded.** |
| selectable | `recursive_composition` | same overlaps as `recursive`, parent rhs \(=1\) | unsat | vs `recursive`: same glues, different parent rhs. Polarity contrast on matched structure. |
| generator only | `flat` | identical to `direct` (no overlaps) | SAT | Not selectable. |

### Coarse-graining (`scale_regime`) — 2-spin integer toy

| Kind | Name | Built structure | Oracle (`fixed`) | Contrast |
|---|---|---|---|---|
| selectable | `direct` | one projector region; recorded depth 1 | True | — |
| selectable | `recursive` | series of \(d\) projector regions | True | vs `direct`: one region vs series. Same polarity. **Confounded.** |
| selectable | `recursive_composition` | series of \(d\) all-ones regions | False | vs `recursive`: same series tree, different weights. Polarity contrast on matched geometry. |
| generator only | `flat` | one all-ones region; recorded depth 1 | False | Not selectable. If it were, it would be a 1-region polarity twin of `direct`, not a flat series. |

Do not call these controls unconfounded because the unit tests pass. The
tests show the generator builds what the table says. They do not show that a
model comparison between `direct` and `recursive` isolates nesting, and they
do not show that `flat` is an experimental arm.

## 4. Evaluation-readiness matrix

| Env | (1) Generator/oracle | (2) Shortcut resistance | (3) Model performance | Ready to score a model? |
|---|---|---|---|---|
| `recursive_holonomy_gluing` | Yes, on selectable regimes. | Yes. Local-only 0 vs reference 1 on REC_COMP. | Unmeasured | Runnable config exists. Blocked on credentials. Do not read (1)–(2) as (3). |
| `recursive_compiler_bootstrap` | Yes. Finite sampled grammar. | Yes. Trust-the-claim 0 vs reference 1. | Unmeasured | Same. |
| `recursive_error_correcting_codes` | Yes. \(\mathbb F_5\) enumerate. | Yes. Local-only 0 vs reference 1. | Unmeasured | Same. |
| `recursive_coarse_graining` | Yes. 2-spin integer tables. | Yes. First-region 0 vs reference 1. | Unmeasured | Same. Toy, not physics. |

## 5. Tests

```
.venv/bin/python -m pytest tests/test_recursive_holonomy_gluing.py \
  tests/test_recursive_compiler_bootstrap.py \
  tests/test_recursive_error_correcting_codes.py \
  tests/test_recursive_coarse_graining.py \
  tests/test_recursive_apps_readiness.py \
  tests/test_recursive_maze_gluing.py tests/test_recursive_distributed_gluing.py \
  tests/test_recursive_epistemic_gluing.py tests/test_recursive_gluing.py \
  tests/test_recursive_gluing_discovery.py tests/test_experiment_arms.py \
  tests/test_latent_registry.py -q
```

**174 passed, 0 skipped.** (151 at `b961ba6` plus 23: workspace coverage
went from 4 all-easy trees to 24 selectable regime × representation trees
(+20) and three regime-selectability tests). Skipped tests are not counted
as passes.

## 6. Model pilot — blocker

Unchanged. No provider credentials in this sandbox. No provider HTTP call.
No local heuristic as a stand-in score. Recipe:
`docs/audits/2026-10-17-four-apps-pilot.json`. Status: **unmeasured**.

## 7. Claims not made

- Models recover latent maps, encodings, codewords, or tables.
- Reference-solver success is structural reasoning by a model.
- These unit tests validate a benchmark.
- Four regimes are available to experiments.
- `direct` vs `recursive` isolates nesting.
- `flat` is a suite-inventory / `--difficulty` level.
- Compiler depth 3 is a harder grammar than depth 2.
- Coarse-graining is physics.
