# Causal structure extension — 15 November 2026

The interactive environment portfolio now includes `causal_structure`, extending
the original request for hidden causal structures and unfamiliar interventions.
The existing nine families and 44 axes were already implemented. This addition
provides a tenth registered family and four more axes.

The agent constructs a causal tree from exact observations and chosen
experiments, then forecasts combined interventions unavailable as experiments.
Every admissible topology initially shares the same observations for a fixed
parity pattern. A submitted graph can represent an unresolved equivalence class;
the scorer distinguishes forecast error, unresolved causal structure, and
intrinsic root randomness.

The controller uses Prüfer trees and forward structural-equation evaluation.
The reference independently uses parent assignments and ancestor walks. Both
are constrained by the same published grammar. No candidate menu or private
ticket is included in policy observations.

## Validation

Node.js 24.19.0: **164 tests passed; zero failed or skipped.** The ten new test
groups cover:

- Independent exact tree counts through all 625 five-variable rooted trees.
- Hand-calculated observational twins and intervention responses.
- Exact posterior weights after informative interventions and under no access.
- All 36 signed three-variable structures with full identification.
- All 35 pairwise axis profiles, including reference execution and replay.
- Unsupported certainty, premature submission, and correlation-only forecasts.
- Graph and forecast validation, equivalent reordered outputs, and atomic
  rejection of malformed or repeated actions.

Local evidence is saved in
`runs/causal-structure-2026-11-15/tests.tap` and `validation.json`, including source
fingerprints. These are instrument checks, not evaluated model episodes.

[Hosted validation run 43700480422](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/43700480422)
passed all 11 jobs at code revision `df8016189779b3e2f813547005feb39f616ae248`:
the regression suite and configured generation/execution/replay for each of the
ten families. Local job metadata is retained in
`runs/causal-structure-2026-11-15/github-validation-jobs.json`.

The separate [repository-wide Python/Docker CI](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/43700480330)
was still executing pytest at 09:49 UTC. The family workflow's success is not a
claim that this broader job passed. The repair report records nine failures
already present in its base revision.

The family includes an editable YAML preset and is enrolled in the provider-free
GitHub validation matrix. The two existing paid campaign profiles retain their
original nine-family cohort. Their `all` selection and source-pinned continuation
semantics remain unchanged.

## Three workstreams

| Workstream | Evidence and remaining boundary |
|---|---|
| Develop families and axes | Nine families already existed; this causal-structure extension adds a concrete missing mechanism. See the [contract and run instructions](../epistemic-families/causal_structure.md). |
| Run models on GitHub | The latest recorded [Atria attempt](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/43680460342) stopped at its first request with `429 quota_exceeded`: zero scored episodes. The active campaign chat is pursuing access recovery. This change dispatches no paid model calls. |
| Repair audited defects and leakage | Repairs are published on `codex/environment-audit-repairs-20261115`; [targeted hosted validation](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/43688496933) passed all five jobs and 423 primary behavioral controls. See the [repair report](2026-11-15-environment-audit-repairs.md) for remaining repository-wide CI failures and limits. |

This family covers bounded deterministic trees with one fair exogenous root.
It does not cover hidden confounding, general DAGs, noisy estimation, or arbitrary
causal mechanisms. Axis names are operational settings, not a measured ordering
of model difficulty. At three nodes some branching settings coincide; without
intervention access, additional credits are inactive.
