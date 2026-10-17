# Four recursive-gluing applications — evaluation-readiness audit

Date: 2026-10-17.
Branch: `arena/1ddc930c-rl-eval-generator`.
Parent commit: `ca274d608f5458e602165cf70effea6af289e5cb`.

This pass hardens the four application environments already on the branch.
It does not add environments. It does not modify maze / distributed /
epistemic / v0 / discovery files.

Passing the tests below is **(1) generator/oracle correctness** and
**(2) shortcut resistance**. It is **not (3) model performance**. The
reference solver composing maps / running interpreters / enumerating
\(\mathbb F_5\) / summing integer tables is not evidence that a language
model does structural reasoning. Unit tests are not benchmark validity.

## 1. Model-facing path

Registry → `generate_env.py` layout → `agent/workspace/{prompt.md,solver.py,visible_tests.py}`.
The judge eval runner (each `files/judge.py`) serializes
`public_instance(...)` into the candidate `solve` payload. `generation.json`
is written at the generated-tree root, not under `agent/workspace`, and is
not copied by `shared/Dockerfile.agent`.

Tests: `tests/test_recursive_apps_readiness.py` walks every regime ×
representation public payload and the rendered agent workspace.

Secret fields that must not enter the payload: `meta`, `composite`,
`expect_fixed`, and (when `representation=inferred`) `maps` / `expanded` /
`encodings` / `perms` / `label_perm` / recode `perm` on compiler stages.

## 2. Concern ledger

### Fixed

| Concern | What changed |
|---|---|
| Holonomy silently lifted `depth` 1→2 on RECURSIVE/REC_COMP and forced DIRECT/FLAT to 1 | Recorded `depth` is the cycle leaf-count requested. REC_COMP at depth 1 is a 1-leaf cycle plus a no-returning-state extra map. |
| Codes `depth` did not add symbols (always 3 length-2 blocks, DIRECT: 1) | `depth` is the number of length-2 blocks. Enumerator \(5^{2d}\). |
| Compiler programs were six hand-listed literals, claimed as if an AST-depth axis | Bounded `add`-grammar over `{0,1,2}`, height `min(depth, 2)`, sample of 6, seed-dependent. Claim is only the listed set. Depth 3 records 2. |
| Compiler inferred payload still carried recode `perm` on `stages` | `public_instance` strips `perm` unless revealed. |
| Coarse RECURSIVE/REC_COMP ignored requested depth (always two regions) | Recursive regimes build `depth` series-composed 2-spin regions. DIRECT/FLAT still one region and record `depth=1`. |
| Coarse agent prompt said “fixed point” | Rephrased to “stable under doubling”; output field remains `fixed`. |
| Holonomy judge docstring named the sheaf axiom | Judge-only wording removed. Agent workspace never contained it. |

### Verified non-issue

| Concern | Evidence |
|---|---|
| `meta` / SAT labels in the candidate payload | Absent from `public_instance` JSON for all four apps, all regimes, revealed and inferred. |
| Theory tokens in the agent workspace after placeholder substitution | `generate_env` workspaces contain none of sheaf / holonomy / Čech / cohomology / monodromy / gluing / `recursive_composition` / `fixed point`. Env directory names do not appear in workspace files. |
| Oracle budget exhaustion treated as unsat | Existing tests still raise `OracleBudgetExceeded`; judges map that to runtime error. |
| Shortcut baselines accidentally solving D-class | Local-only / trust-the-claim / first-region baselines remain SAT/`equivalent=True`/`fixed=True` on REC_COMP; reference is the opposite. Held-out seeds `10000+`. |
| Isomorphic rename flipping the verdict | Relabel preserves SAT/equivalence/`fixed`. Changing the extra map / parent rhs / claimed decoder / region weights flips it. |
| Boolean fields accepted as truthy strings | Existing `type(value) is bool` checks still pass. |
| Coarse-graining silently broadened | Still a 2-spin nonnegative integer toy. |

### Unresolved (documented, not claimed away)

| Concern | What it can and cannot establish |
|---|---|
| Directory `recursive_holonomy_gluing` contains `holonomy` | Host/registry name. Not present in the Docker agent workspace. A human who sees the checkout path is not a clean subject. |
| Codes public field `glues` | Schema identifier. Prompt describes overlap constraints; the key is unchanged so existing certificates keep working. |
| Holonomy DIRECT vs FLAT | Both are the identity cycle of length `depth`. They are SAT-identical. They do **not** establish nesting-versus-flat. Nesting (`root=node`) only appears on RECURSIVE/REC_COMP at depth ≥ 2. |
| Codes DIRECT vs FLAT | Both have no cycle overlaps. SAT-identical independent blocks. Overlaps are the recursive regimes. |
| Compiler DIRECT vs FLAT | Both are a single compile stage. Stage count is `bootstrap_regime`, not `depth`. |
| Coarse FLAT | One all-ones region, not a flat presentation of a series. DIRECT vs FLAT is a weight choice, not geometry. |
| Codes inferred coordinate perm | `H=[1 1]` is symmetric: visible calibration does not uniquely determine a length-2 perm. Inferred is a weak presentation axis here. |
| Coarse inferred `label_perm` | A 1-bit swap of `{0,1}`. Not a deep hide. |
| Compiler depth cap | Grammar height saturates at 2. Requested 3 records 2. No claim of unbounded AST generalization. |
| Coarse DIRECT/FLAT vs the depth axis | Requested depth 3 still builds one region and records 1. The axis is honest only on recursive regimes. |
| Explicit expansion | Holonomy grade item (`representation=explicit` + `expanded`). Not a config level. |
| Model performance | Unmeasured. See §5. |

## 3. Evaluation-readiness matrix

| Env | (1) Generator/oracle | (2) Shortcut resistance | (3) Model performance | Ready to score a model? |
|---|---|---|---|---|
| `recursive_holonomy_gluing` | Yes. Compose + enumerate returning states. Depth = cycle leaf count. | Yes. Local-only always SAT; D-class unsat; reference unsat. Accuracy 0 vs 1 on held-out REC_COMP. | Unmeasured | Runnable config exists. Blocked on credentials. Do not read (1)–(2) as (3). |
| `recursive_compiler_bootstrap` | Yes. Interpreters on a finite sampled grammar. Path decoder can fail while each stage is locally ok. | Yes. Trust-the-claim baseline `equivalent=True` on REC_COMP; reference `False`. | Unmeasured | Same. |
| `recursive_error_correcting_codes` | Yes. \(\mathbb F_5\) matvec + enumerate. `depth` blocks. Local kernels nonempty, stacked unsat on REC_COMP. | Yes. Local-only SAT on D-class; reference unsat. | Unmeasured | Same. Enumerator \(5^{2d}\) (15625 at depth 3). |
| `recursive_coarse_graining` | Yes. Exact 2-spin integer tables. Recursive depth = number of series regions. | Yes. First-region baseline claims `fixed=True` on REC_COMP; reference `False`. | Unmeasured | Same. Toy, not a physical RG model. |

A/B/C/D (`direct` / `recursive` / `flat` / `recursive_composition`) are
implemented as regime strings. SAT polarity is the regime, not a relabel of
the same instance as “harder”. Revealed vs inferred is a presentation axis
whose strength differs by env (see unresolved). Do not treat DIRECT/FLAT as
an unconfounded nesting control.

## 4. Tests

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

**151 passed, 0 skipped.** (136 at `ca274d6` plus 15 new depth/leakage/shortcut
regressions. Skipped tests are not counted as passes.)

Per-file additions: one depth/payload test in each of the four env modules;
`tests/test_recursive_apps_readiness.py` (11 cases including four generated
workspaces).

Scaling after the depth fixes: `docs/audits/2026-10-17-four-apps-scaling.json`.
Held-out shortcut JSON under `docs/audits/2026-10-16-*-baselines.json` was
re-emitted by the existing tests and still records local-only unsat/non-fixed
accuracy 0, reference 1.

## 5. Model pilot — blocker

`tools/provider_preflight.py` with no `--provider` and no `secret_key.json`:

```json
{"providers": [], "reachable_count": 0, "failure_count": 0, "paid_fallback": false}
```

No API keys were present in the process environment. No provider HTTP call
was made. No local heuristic was used as a stand-in score.

Runnable recipe (do not run until a no-cost endpoint is verified):
`docs/audits/2026-10-17-four-apps-pilot.json`.

Status: **unmeasured**.

## 6. Claims not made

- Models recover latent maps, encodings, codewords, or tables.
- Reference-solver success is structural reasoning by a model.
- These unit tests validate a benchmark.
- DIRECT vs FLAT isolates nesting.
- Compiler depth 3 is a harder grammar than depth 2 (it is the same height-2 sample cap).
- Coarse-graining is physics.
