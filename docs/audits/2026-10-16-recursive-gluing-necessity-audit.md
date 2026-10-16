# Phase 0 necessity audit: recursive local-to-global gluing

Date: 2026-10-16.
Branch: `arena/1ddc930c-rl-eval-generator`.
HEAD at audit time: `d365d9e407b29ea4a5764cca0fe87e7f4d53c861`
(`add maze, distributed, and epistemic recursive gluing families`).

This document is the mandatory Phase 0 record for `recursive_gluing_4.md`.
Environment code was not edited in order to produce it. Analysis lives in
`tools/recursive_necessity_baselines.py` (not imported by any judge).
Raw numbers: `docs/audits/2026-10-16-recursive-gluing-necessity-measurements.json`.

Claims are tagged `[formal]`, `[tested]`, `[reference-solver only]`, or
`[requires model runs — not done]`.

## 0.1 Repository state

Commands run:

```text
git status --short
git branch --show-current
git rev-parse HEAD
git log --oneline -15
git stash list
```

Recorded output:

```text
?? tools/recursive_necessity_baselines.py
---
arena/1ddc930c-rl-eval-generator
---
d365d9e407b29ea4a5764cca0fe87e7f4d53c861
---
d365d9e add maze, distributed, and epistemic recursive gluing families
c50f128 measure compact vs expanded recursive gluing and audit the claims
ee095ed rewrite recursive_gluing_discovery as a compact recursive grammar
9f6ba2f add recursive_gluing_discovery as the v0 control's research sibling
93cc8dc add recursive_gluing environment
8736607 campaign re-arm: measured cron cadence and ledger progress replace two unchecked deferrals (mirror of 3d6e743)
---
(empty stash)
```

`docs/audits/` did not exist. No reset, discard, or checkout of another
branch was performed. Uncommitted analysis files were kept.

### Layout (actual paths)

| Path | Role |
|---|---|
| `envs/cat_theo/recursive_maze_gluing/` | Maze family (config + `files/{network,judge,prompt,solver,visible_tests}.py`) |
| `envs/cat_theo/recursive_distributed_gluing/` | Distributed family |
| `envs/cat_theo/recursive_epistemic_gluing/` | Epistemic family |
| `envs/cat_theo/recursive_gluing/` | v0 expanded-CSP control; **read-only** this pass |
| `envs/cat_theo/recursive_gluing_discovery/` | Compact-grammar sibling; **read-only** this pass |
| `docs/decisions/2026-10-16-sheaf-recursive-reasoning.md` | Design note |
| `envs/registry.yaml` | Names at lines 37–41 |
| `envs/interventions.yaml` | Vocabulary only (see below) |
| `tests/test_recursive_{maze,distributed,epistemic,gluing,gluing_discovery}.py` | Family tests |

`tests/test_cat_theo.py` does **not** exist. Registry coverage is in each
family's own test module.

### Controls inspected, not modified

- `recursive_gluing` and `recursive_gluing_discovery` remain historical
  controls. Their semantics are relation composition / compact grammar, not
  maze routes, distributed traces, or modal models. They were not included
  in the 200-instance domain sample. `[tested]` for presence only.
- `envs/interventions.yaml` is the shared vocabulary. None of the three
  domain `config.yaml` files declare an `interventions:` block, so no
  overlay id is supported by those environments. `[tested]`

### Registry names `[tested]`

`envs/registry.yaml` lines 37–41:

- `recursive_gluing`
- `recursive_gluing_discovery`
- `recursive_maze_gluing`
- `recursive_distributed_gluing`
- `recursive_epistemic_gluing`

No collisions.

## 0.2 Baseline measurements

Command:

```text
.venv/bin/python tools/recursive_necessity_baselines.py --n 216 \
  --json docs/audits/2026-10-16-recursive-gluing-necessity-measurements.json
```

Sample construction (deterministic, no hidden `meta` as input):

- Maze: 216 instances = full product of depths `{1,2,3}` × regimes
  `{tree, cyclic_sat, cyclic_unsat}` × opacities `{transparent, opaque}` ×
  ambiguities `{clean, decoy}`, seeds `0..215`. Ground truth:
  `maze_satisfiable` (`network.py` L419).
- Distributed: 216 instances = depths `{1,2,3}` × regimes × opacities,
  seeds `0..215`. Ground truth: `job_satisfiable` (L415).
- Epistemic: 216 instances = depths `{1,2,3}` × regimes × opacities ×
  orders `{0,1,2}`, seeds `0..215`. Two ground-truth bits exist
  (`query_value` L281, `bundle_possible` L286). Combined **task SAT** is
  defined as “query holds at `actual`, and if a bundle is present it is
  possible”. TREE instances have `bundle is None`, so the combined bit is
  exactly `query_value`.

Accuracy and agreement coincide for every baseline below: the predictor
emits the same Boolean as the domain SAT bit. They are reported as equal
numbers, not because failures were dropped. `[tested]`

### Maze (`recursive_maze_gluing`) — 180 SAT / 36 UNSAT

| Baseline | Accuracy = agreement | UNSAT acc | SAT acc | Balanced |
|---|---|---|---|---|
| B0 local walks | 0.833 | **0.000** | 1.000 | 0.500 |
| B1 shaft interfaces | 0.833 | **0.000** | 1.000 | 0.500 |
| Bflat permissive child | 0.833 | 1.000 | 0.800 | 0.900 |
| Bk0 (= Bflat) | 0.833 | 1.000 | 0.800 | 0.900 |
| Bk1 depth≤1 | 1.000 | 1.000 | 1.000 | 1.000 |
| Bk2 depth≤2 | 1.000 | 1.000 | 1.000 | 1.000 |
| M public flip-sum = 0 | 0.500 | 1.000 | 0.400 | 0.700 |
| Majority constant (SAT) | 0.833 | 0.000 | 1.000 | 0.500 |

B0: every tile has an entrance-to-exit walk on its own edges.
B1: B0 plus every shaft’s `from`/`return` lie in the parent rooms and the
named child (if present) is itself walkable. Orientation / sealing /
edge-use are **not** checked.
Bflat: each shaft is replaced by a skip edge carrying only the shaft’s
flip; parent corridor flips are kept; sealing is dropped because the child
is assumed to return. Implemented by calling `maze_satisfiable` on that
foil, not by guessing.
M: SAT iff the public flip-sum is 0. `meta` is stripped by `public_maze`
(L38–39, `PUBLIC_KEYS` L22) and was not used.

Smallest B0/B1 miss (id 8, seed 8, depth 1, `cyclic_unsat`, transparent,
clean): keep `dock-a-b-c-door` with `a→b` flip 1, crypt `entry-hall-exit`
unflipped, start/goal orientation 0. Every tile is locally walkable and
the shaft at `c` is well-typed, so B0 = B1 = SAT. Ground truth UNSAT:
the unique simple root walk has orientation 1. `[tested]`

Bflat UNSAT accuracy is 1.0 on this sample because the obstruction lives
on the **parent** keep, not in a child. Bflat’s SAT misses (id 9, seed 9,
`cyclic_unsat` + `decoy`, truth SAT / Bflat UNSAT) occur because the decoy
`pit` corridor carries flip 1; a real route can XOR the keep cocycle by
descending into `pit`. Flattening turns both shafts into 0-flip skips, so
that cancellation disappears. That is a SAT miss, not an UNSAT miss.
`[tested]`

Bk1 = Bk2 = ground truth on this sample: every generated maze already
exposes the keep at depth 1. Recursion is required operationally (the
exit is sealed until a child is traversed; see `replay_route` L257–261
and `_must_clear` L225) but depth truncation at 1 does not change the
SAT bit. `[tested]`

### Distributed (`recursive_distributed_gluing`) — 144 SAT / 72 UNSAT

| Baseline | Accuracy = agreement | UNSAT acc | SAT acc | Balanced |
|---|---|---|---|---|
| B0 nonempty programs | 0.667 | **0.000** | 1.000 | 0.500 |
| B1 send/recv endpoints | 0.667 | **0.000** | 1.000 | 0.500 |
| Bflat permissive child | 0.444 | 0.667 | 0.333 | 0.500 |
| Bk0 root only | 0.667 | 0.000 | 1.000 | 0.500 |
| Bk1 | 0.778 | 0.333 | 1.000 | 0.667 |
| Bk2 | 0.889 | 0.667 | 1.000 | 0.833 |
| M “no lock+recv” | 0.667 | 1.000 | 0.500 | 0.750 |
| Majority constant (SAT) | 0.667 | 0.000 | 1.000 | 0.500 |

B0: every worker program is nonempty.
B1: B0 plus every `send:`/`recv:` names an existing parent or child.
No lock/mailbox simulation.
Bflat: every non-root worker is replaced by `[compute, send:parent]`
(no lock). Then `job_satisfiable` on the foil. Oracle-budget exhaustion
would have been recorded as “not unsat”; it did not occur. `[tested]`

Smallest B0/B1 miss (id 4, seed 4, depth 1, `cyclic_unsat`, transparent):
root `[spawn, lock, recv:child, send:child, unlock]`, leaf
`[lock, recv:parent, send:parent, unlock]`, `lock_count = 1`. Locally
typed, pairwise endpoints exist, B0 = B1 = SAT. Ground truth UNSAT:
mutex deadlock. Bflat predicts SAT on this instance (permissive leaf
never takes the lock). `[tested]`

M (public “program contains both `lock` and `recv:`”) is a syntactic
deadlock shape: UNSAT acc 1.0, SAT acc 0.5, because `cyclic_sat` also
uses lock and recv, in an order that completes. It is not a hidden
label. `[tested]`

### Epistemic (`recursive_epistemic_gluing`)

Combined task bit (query ∧ bundle): 48 SAT / 168 UNSAT out of 216.
Bundle present on 144 instances (72 possible / 72 impossible).

**Combined task SAT** (query must hold; bundle, if present, must be possible):

| Baseline | Accuracy = agreement | UNSAT acc | SAT acc | Balanced |
|---|---|---|---|---|
| B0 local worlds exist | 0.222 | **0.000** | 1.000 | 0.500 |
| B1 pairwise outer cells | 0.556 | **0.429** | 1.000 | 0.714 |
| Bflat drop inner frames | 1.000 | 1.000 | 1.000 | 1.000 |
| Bk0 / Bk1 / Bk2 | 1.000 | 1.000 | 1.000 | 1.000 |
| M “no bundle or equal worlds” | 0.667 | 0.714 | 0.500 | 0.607 |
| Majority constant (UNSAT) | 0.778 | 1.000 | 0.000 | 0.500 |

**Bundle gluing bit only** (144 instances that have a bundle; ground truth
`bundle_possible`):

| Baseline | Accuracy | UNSAT acc | n_unsat / n_sat |
|---|---|---|---|
| B1 pairwise outer cells | **1.000** | **1.000** | 72 / 72 |

That second table is the gluing question the design note describes
(empty intersection of two cells). With exactly two agents, pairwise
intersection **is** the global intersection. `[tested]` `[formal]`

Bflat / Bk agree with the combined task on **every** sampled instance.
Cause, from source not from a failed run: `bundle` is interpreted only
on the outermost frame (`bundle_possible` L286–309), and the order-2
query is `K_ann K_bob q` which is already false on the inner S5 frame
(Bob cannot distinguish `u0`/`u1` while `q` holds only at `u0`), so
dropping the inner frame does not change the Boolean. The existing test
`test_truncating_depth_changes_nested_query` only checks that `q` is
absent from a depth-1 outer frame and that the flattened checker
agrees; it does **not** assert that `query_value` differs. `[tested]`

Smallest combined-task B1 miss (id 1, seed 1, depth 1, `tree`, order 1):
no bundle, query `["K","ann","p"]` is false at `w0` (Ann’s cell is
`{w0,w1}`, `p` only at `w0`). B1 treats a missing bundle as SAT.
This is a modal miss, not a gluing miss. `[tested]`

Smallest bundle obstruction (seed 12, depth 1, `cyclic_unsat`, order 0):
Ann cell `{w0,w1}` from report `w2` wait — report `ann: w2` gives cell
`{w2}`; `bob: w0` gives `{w0}`; intersection empty. Each cell nonempty.
B1 (two agents) predicts UNSAT and is correct. `[tested]`

### What the three families do and do not separate

| Distinction | Maze | Distributed | Epistemic (current sample) |
|---|---|---|---|
| Local SAT vs global SAT | Yes (B0 UNSAT acc 0) | Yes (B0 UNSAT acc 0) | Bundle: yes (B0 UNSAT acc 0). Combined task: confounded with false `K` queries |
| Pairwise vs global | Yes (B1 UNSAT acc 0; obstruction is holonomy + sealing, not a 2-set mismatch) | Yes (B1 UNSAT acc 0; obstruction is a 2-agent mutex cycle, but pairwise endpoint typing does not see it) | **No** for the bundle bit (B1 UNSAT acc 1.0). Two agents ⇒ pairwise = global |
| Flattening vs real recursion | Weak on UNSAT (parent XOR). SAT decoy routes can require a nested flip | Partial (Bflat UNSAT acc 0.667; deadlock at the root handshake is sometimes flattened away) | **No** on this distribution (Bflat acc 1.0) |
| Depth-1 vs deeper | Bk1 already matches GT | Bk1/Bk2 still miss some deeper deadlocks | Bk* match GT |

Hypotheses rejected or narrowed:

- “Maze UNSAT needs deep recursion.” False for the SAT **bit**: Bk1 = GT.
  Nested traversal is still required of a SAT **witness** (`descend`/`ascend`).
  `[tested]`
- “Epistemic nested `K` on this generator changes the answer when flattened.”
  False for the current query family. `[tested]`
- “Distributed B1 already sees the deadlock.” False. `[tested]`

## 0.3 Judge independence

Shared pattern in all three `files/judge.py`: generate grade instances,
call `public_*` (strips `meta`), run the candidate, then
`verify_certificate`. `OracleBudgetExceeded` becomes `judge_runtime_error`
with the text “not treated as unsat” (maze L104–110, distributed L96–102,
epistemic L103–109). Crashes and parse failures fail the check; they are
not counted as correct UNSAT. `[tested]` from source.

### Maze

- SAT path: `verify_certificate` L442–451 parses the certificate, then
  `replay_route` L229–289 walks `move`/`descend`/`ascend` edge-by-edge,
  rejects reused edges, sealed exits, bad orientation, overlong traces.
- UNSAT path: the same function calls `maze_satisfiable` L419, which is
  `shortest_route(...) is not None`. `arm_reference` L454 is
  `reference_certificate`, which also calls `shortest_route`.
- Budget: `shortest_route` L372, `max_nodes=50_000`, raises
  `OracleBudgetExceeded` at L394–396 rather than returning `None`.
- `meta` is not in `PUBLIC_KEYS` and is not read by the verifier.
- No import of `solver.py` (confirmed by `test_oracle_independent` in
  `tests/test_recursive_maze_gluing.py`).

**Limitation, not a demonstrated correctness bug.** Monkeypatching
`maze_satisfiable` would take down both the reference and the UNSAT
side of the judge. SAT replay would still work. No independence
regression test of that form exists yet.

### Distributed

- SAT path: `verify_certificate` L441–454 replays the trace
  (`replay_trace` L151) under FIFO mailboxes and a mutex; optional
  `result` must match the trace, not `input+1`.
- UNSAT path: `job_satisfiable` L415 = `shortest_trace is not None`.
  Same coupling as maze.
- Budget: `shortest_trace` L299, `max_nodes=80_000`, raise at L337–339.
- `arm_numbers_only` L458–461 is a baseline, not the judge.

Same limitation. No demonstrated wrong verdict found.

### Epistemic

- `verify_certificate` L313–328 calls `reference_certificate` L297–309,
  which recomputes `query_value` and `bundle_possible`. There is **no**
  SAT witness to replay: the candidate emits Booleans, and the judge
  compares them to a second evaluation of the same functions.
- A second checker `flatten_model` L240 / `cross_check_flat` L331 exists
  but is **not** used by `verify_certificate`.
- Budget: `eval_formula` L217–219 raises `OracleBudgetExceeded` on a
  50_000-step counter (`query_value` L281–283).
- Bundle SAT/UNSAT is a finite intersection of at most three outer
  worlds; no search budget applies.

This is independent of generator `meta` and of `solver.py`. It is **not**
independent of `reference_certificate` / `arm_reference`: a monkeypatch
of those names currently breaks the judge. That is a coupling to report,
not a wrong answer on the supported class. `[tested]` from source.

### Decision on 0.3

No judge was shown to accept a bad SAT witness, to treat budget
exhaustion as UNSAT, or to read hidden labels. The stop-early rule
(“demonstrated correctness or independence **defect** → fix that env
only and stop”) is **not** triggered. The coupling above is a Phase-4
item for the selected environment.

## 0.4 Mathematical claims

`docs/decisions/2026-10-16-sheaf-recursive-reasoning.md` already states
the correct distinction (paragraphs 3–5): admissible configurations form
a **subpresheaf of a sheaf of raw assignments**; an unsat instance is
**absence of a global section of that constrained presheaf**, not a
failure of the sheaf axiom for a structure that is already a sheaf.
`[formal]`

No addendum is required to retract a false axiom claim. An addendum **is**
required after the selected-environment work, because the current
epistemic obstruction (“two nonempty cells with empty intersection”) is
pairwise, and the note’s correspondence table should record that.
History of the original note is preserved.

Transports:

- Maze: orientation in \(\mathbb{Z}/2\mathbb{Z}\) along edges and shafts;
  composition is XOR; a simple-edge walk cannot cancel a 1-cocycle by
  repeating an edge (`replay_route` L254–256). This is a finite local
  system on a graph, not a Čech cohomology theory of an arbitrary cover.
  `[formal]`
- Distributed: no geometric transport; obstruction is an operational
  wait-for cycle on a mutex plus FIFO mailboxes.
- Epistemic: no holonomy. Bundle possibility is occupancy of a common
  world. Nested frames are a product of small S5 models, not DEL.

## Phase 0 decision

1. No demonstrated judge correctness/independence defect → do not stop.
2. B1 accuracy on the UNSAT sample:
   - maze: **0.000** (36 UNSAT)
   - distributed: **0.000** (72 UNSAT)
   - epistemic combined task: **0.429** (168 UNSAT)
   - epistemic bundle bit (the gluing negative): **1.000** (72 UNSAT)
3. Highest B1-on-UNSAT is **epistemic** under either reading. Tie-break
   (Bflat agreement, then maze > distributed > epistemic) is not needed.
4. Not all three already establish the intended distinctions.
   Epistemic currently fails pairwise-vs-global and flattening-vs-recursion.

**Selected environment: `recursive_epistemic_gluing`.**

Reason: its supposedly global negatives are exactly the pairwise
2-agent cell mismatches, so pairwise reasoning already solves the gluing
bit. Phases 1–6 apply only here. Maze and distributed, and both v0
controls, stay byte-for-byte.

Follow-up not done in this pass (non-selected families): maze still lacks
a nested-only UNSAT class (parent XOR is visible at depth 1); distributed
deadlock is a 2-process mutex cycle that a lock-aware pairwise analysis
might still catch. Those are out of scope by the decision rule.
