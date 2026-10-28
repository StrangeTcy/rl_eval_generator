# Recursive gluing experimental design and run manifest

Updated: 2026-10-28
Status: implementation revision; runtime validation and model experiments pending.

This document describes the current code. The earlier audit is preserved in
`2026-10-26-recursive-gluing-experimental-design.historical.md`. The detailed
implementation and scientific-readiness report is
[`2026-10-28-recursive-structural-rebuild.md`](../reports/2026-10-28-recursive-structural-rebuild.md).

## Claims are separate

The five claims are competence, shortcut resistance, structural inference,
compositional generalization, and cross-domain transfer. They are not one
ordered score. Perfect task performance establishes only successful behavior
on those verified inputs. A representation certificate permits a more specific
observation, but does not identify an internal reasoning procedure.

The study profile now records an evidence contract and joint outcomes of
matched hidden controls. Missing checks remain unobserved. A failed combined
certificate check is not automatically a wrong satisfiability decision.

Within-episode control success is not a training/evaluation generalization
result. Cross-domain transfer is unmeasured. All nine PASS thresholds require
every correctness check; partial scores remain diagnostic.

## Implemented controls

| Environment | Matched controls or representation check | Rival |
|---|---|---|
| recursive_gluing | nonfunctional relation cycle; closing overlap intervention | expanded CSP, spanning-forest ablation |
| recursive_gluing_discovery | branching relations; closing intervention; coordinate twins | compact relation iteration, independent expanded CSP, copy-leaf |
| recursive_maze_gluing | mixed tile schedules; orientation intervention | full-state BFS, orientation ablation |
| recursive_distributed_gluing | lock capacity 1/2; role/address presentations | scheduler BFS, capacity ablation |
| recursive_epistemic_gluing | modal endpoint atom; inner report intersection | finite modal evaluation, actual-facts control |
| recursive_compiler_bootstrap | authored L1 source, bootstrap provenance, sampled semantics, shifted opcodes | known compiler program, decoder-only ablation |
| recursive_error_correcting_codes | transformed coordinates/units; ambiguity classes; parent RHS | field elimination, exhaustive coordinate search |
| recursive_coarse_graining | binary quotient commutation and predictions; changed microscopic edge | matrix computation and partition enumeration |
| recursive_holonomy_gluing | ordered loop maps, flatness, all common fixed states | algebraic composition, direct finite-state transport |

These controls are code, not executed results. Reference-conditioned negative
controls are labelled as such; they are not independent solvers. Direct
algorithms that solve the task are legitimate competing explanations.

The compiler implementation is L1 source compiled to a VM with no compilation
primitive. The candidate supplies source and each requested stage; the public
payload contains the trusted seed executable, not that source. A separate
source interpreter checks sampled semantics. This is a small bootstrap task,
not proof of correctness on all programs. The legacy add/decoder task remains
an explicitly separate control.

The transport task distinguishes agreement of two path maps from identity of
both loops, and distinguishes non-flatness from nonexistence of global
sections. Its topology distribution is still limited to two loops.

## Existing study architecture

Use `tools/recursive_gluing_study.py` for planning/reporting and the existing
exact-instance gate for positive/negative certification. Profile version is 2.
The diagnostic matrix retains 18 episode specifications. The exploratory
family screen retains three vectors for each of eight candidate gate members.
Holonomy remains excluded. Compiler legacy inferred-decoder references remain
pinned to revealed; codes and coarse-graining public references now recover
their calibrated presentations.

Matrix cells include multiple hidden controls in one episode. Analyze their
named checks, not an aggregate episode-score difference as if it were a
single-factor causal effect. The JSON manifest recomputes hidden-check
accounting from current source declarations and marks runtime validation
outstanding.

## Reproducible rival execution

The existing runner now supports:
```text
python tools/recursive_necessity_baselines.py --structural --depth 2 --seed 41 --json structural-rivals.json
```
Run this only in an isolated execution environment. It evaluates the existing
grading inputs through public interfaces, records source/input hashes and
solver times, and keeps accepted, rejected, solver-budget, oracle-budget, and
error outcomes separate. It reports no model capability conclusion.

The manual workflow
`.github/workflows/recursive-structural-validation.yml` defines hosted
Python 3.11 testing and this rival run without provider credentials. It has
not been dispatched. Larger depth/seed sweeps, resource comparisons, and
exact-instance container certification remain outstanding.

## Readiness

The changes are not scientifically mature or empirically validated.
The source review artifact is
`docs/reports/2026-10-28-structural-source-review.json`. Its delimiter and
field checks do not establish Python syntax or behavior.

Before a confirmatory study: execute all regressions and gates; inspect
rival failure modes; preregister disjoint training/evaluation compositions;
test calibration identifiability; expand formal families/topologies; and
design a source/target transfer intervention. Paid provider campaigns require
separate explicit authorization. No such campaign has been run for this
revision.
