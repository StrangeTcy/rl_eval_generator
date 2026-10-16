# Recursive gluing 4 — necessity pass, final report

Date: 2026-10-16.
Branch: `arena/1ddc930c-rl-eval-generator`.

## 1. Repository state

| | |
|---|---|
| Starting HEAD | `d365d9e407b29ea4a5764cca0fe87e7f4d53c861` |
| Starting worktree | clean except later untracked analysis files |
| Audit commit | `3a87f78fbd11a92a3055c26e77a53a9a5b3d4008` (Phase 0 only; no environment code) |
| This pass | epistemic family + tests + notes (see `git diff --stat`) |
| Branch | `arena/1ddc930c-rl-eval-generator` |
| Stash | empty |
| Controls | `recursive_gluing`, `recursive_gluing_discovery`, maze, distributed **byte-for-byte** |

Phase 0 commands are recorded in
`docs/audits/2026-10-16-recursive-gluing-necessity-audit.md`.
No reset, merge onto `main`, or force-push.

## 2. Phase 0 decision `[tested]`

216 deterministic instances per family. B1 accuracy on UNSAT:

| Family | UNSAT n | B1 UNSAT acc | Bflat agreement |
|---|---|---|---|
| maze | 36 | 0.000 | 0.833 |
| distributed | 72 | 0.000 | 0.444 |
| epistemic combined task | 168 | 0.429 | 1.000 |
| epistemic bundle bit | 72 | **1.000** | 1.000 |

Highest B1-on-UNSAT: **epistemic**. No demonstrated judge correctness
defect (budget exhaustion is `judge_runtime_error`; SAT maze/distributed
witnesses are replayed; epistemic compared Booleans via the same domain
functions). Stop-early rule not triggered. Not all three families already
separated pairwise-vs-global and flattening-vs-recursion.

**Selected: `recursive_epistemic_gluing`.** Maze and distributed left
read-only.

## 3. Selected environment and why

Two-agent outer bundles make pairwise intersection identical to the
global intersection, so a pairwise solver already classified every
gluing negative. Nested frames did not change the combined task bit on
the Phase-0 sample (`K_ann K_bob q` is false with or without the inner
frame). The family was the one whose “global” negatives were most
susceptible to pairwise reasoning.

## 4. Local-to-global formalization `[formal]`

Developer note:
`docs/decisions/2026-10-16-epistemic-recursive-contract.md`.
Addendum on the original sheaf note (history preserved).

Raw world-assignment data on a discrete set of worlds is a sheaf:
compatible local choices of a world glue uniquely. Admissible reports
form a **constrained subpresheaf** \(S\). Unsatisfiability is
**emptiness of \(S(A)\)**, not a failure of the sheaf axiom.

- NEG-pairwise: some 2-wise cell intersection is empty.
- NEG-deep: every 2-wise and 3-wise intersection of four cells is
  nonempty, \(S(A)=\emptyset\). Finite nerve of a 4-point cover; not a
  cohomology theory of an interesting space.
- NEG-recursive: outer \(S\) nonempty, inner reports empty; flattening
  drops the inner frame and wrongly predicts SAT.
- POS-recursive: atom `q` holds only on an inner frame. Ordinary nested
  model checking, not a cohomological obstruction.

## 5. Judge correctness and resource contract `[tested]`

`verify_certificate` recomputes `query_value` by `eval_formula` and
bundle possibility by finite set intersection. It does not call
`reference_certificate` or `arm_reference` (AST + monkeypatch tests).
SAT bundle claims must exhibit `joint_world` / `joint_inner` in every
cell. Depth-1 queries are cross-checked against `flatten_model`.
Modal evaluation has a 50_000-step budget;
`OracleBudgetExceeded` is not unsat. No wall-clock assertions.

## 6. Smallest examples `[tested]`

**NEG-deep** (`handwritten_neg_deep`): four agents, worlds
`{w0,w1,w2,w3}`, cells the 3-subsets, reports so that every triple
meets and all four do not. `query_value=true`, `bundle_possible=false`.
Judge accepts `{"query_value": true, "bundle_possible": false}` and
rejects a fake `joint_world`.

**NEG-recursive** (`handwritten_neg_recursive`): outer cells
`{w0,w1}` and `{w1,w2}` (meet at `w1`); inner reports `u0` vs `u1` on
discrete partitions. Task UNSAT; flattening SAT.

**FLIP:** `flip_neg_recursive` assigns every inner report the first
agent’s inner world. Task becomes SAT with
`joint_world='w1'`, `joint_inner='u0'`.

**Presentation twin:** `presentation_twin` relabels worlds and shuffles
agent/bundle key order; verdict and judge result preserved.

## 7. Tests

```text
.venv/bin/python -m pytest tests/test_recursive_epistemic_gluing.py \
  tests/test_recursive_maze_gluing.py tests/test_recursive_distributed_gluing.py \
  tests/test_recursive_gluing.py tests/test_recursive_gluing_discovery.py \
  tests/test_experiment_arms.py tests/test_latent_registry.py -q
```

Result: **99 passed, 0 skipped.** Existing epistemic tests kept.
Thirteen Phase-6 categories are explicit test functions
`test_1_…` … `test_13_…`.

## 8. Held-out baselines `[tested]`

30 instances per class, seeds `10000..10029` (dev `0..29`).
Raw table: `docs/audits/2026-10-16-epistemic-heldout-metrics.json`.

| Class | B0 local | B1 pairwise | Bflat | Bk2 |
|---|---|---|---|---|
| POS-plain | 1.0 | 1.0 | 1.0 | 1.0 |
| POS-recursive | 1.0 | 1.0 | **0.0** | 1.0 |
| NEG-local | 1.0 | 1.0 | 1.0 | 1.0 |
| NEG-pairwise | 0.0 | 1.0 | 1.0 | 1.0 |
| NEG-deep | 0.0 | **0.0** | 1.0 | 1.0 |
| NEG-recursive | 0.0 | 0.0 | **0.0** | 1.0 |

Balanced held-out (60 SAT / 60 UNSAT): majority 0.5, B1 0.75, Bflat
0.625, public-feature metadata 0.875. Metadata is strong because
4-world/4-agent public shape is common in NEG-deep; it is not perfect
because half of POS-plain uses the same shape with a nonempty 4-wise
intersection. That result is left standing. Labels, seeds, and scoring
were not tweaked to force chance. `[tested]`

No external-model campaign. `[requires model runs — not done]`

## 9. Limitations and follow-up

- Maze and distributed still have B1 UNSAT accuracy 0 on their own
  samples, but were not modified (decision rule). Maze UNSAT is a
  parent XOR visible at depth 1; nested SAT witnesses still must
  descend. Distributed deadlock is a 2-process mutex cycle that
  endpoint-typing does not see.
- Epistemic nesting is a product of small S5 frames, not DEL or common
  knowledge. Inner frames do not depend on the outer world.
- Agent prompt is linted after placeholder substitution. The source
  directory name `recursive_epistemic_gluing` contains the stem
  `gluing`; the rendered agent workspace does not. `[tested]`
- Axis id `gluing_regime` remains in `config.yaml` (harness, not the
  agent prompt).
- This pass implements a task and a verified judge/reference solver.
  It does **not** demonstrate model capability.

## Claims ledger

| Claim | Tag |
|---|---|
| Phase-0 B1/Bflat/Bk/M numbers | `[tested]` |
| Sheaf axiom vs empty global section of a constrained presheaf | `[formal]` |
| NEG-deep 3-wise nonempty, 4-wise empty | `[formal]` `[tested]` |
| NEG-recursive flattening SAT / true UNSAT | `[tested]` |
| POS-recursive inner atom, flattening false | `[tested]` |
| Judge independent of `arm_reference` / `reference_certificate` | `[tested]` |
| Budget exhaustion is not unsat | `[tested]` |
| Reference solver agrees with judge on generated classes | `[tested]` |
| Metadata probe 0.875 on balanced held-out | `[tested]` |
| Models discover latent sheaf structure | `[requires model runs — not done]` |
| Maze/distributed families still byte-identical | `[tested]` |
