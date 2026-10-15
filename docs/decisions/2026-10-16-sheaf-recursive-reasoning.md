# Sheaf-theoretic recursive reasoning: three domain families

Date: 2026-10-16.
Controls kept: `recursive_gluing` (expanded CSP) and `recursive_gluing_discovery`
(compact grammar). This note justifies three additional families:

- `recursive_maze_gluing`
- `recursive_distributed_gluing`
- `recursive_epistemic_gluing`

Agent-facing prompts do not use the words below. This note does.

## Constraint presheaf, not a decorative sheaf

Let \(X\) be a finite base (rooms of a maze, agents in a job, worlds of a
frame). A cover \(\{U_i\}\) is a family of contexts. A **constraint presheaf**
\(F\) assigns to each \(U\) a set \(F(U)\) of *admissible* local configurations
and restriction maps \(\rho_{V\leftarrow U}: F(U)\to F(V)\) for \(V\subseteq U\).

The sheaf axiom would say: every pairwise-compatible family \((s_i\in F(U_i))\)
extends uniquely to a global section of \(F\). The tasks here are interesting
precisely because the *admissible* configurations form a **subpresheaf of a
sheaf of raw assignments**. Raw walks, raw interleavings, and raw world-chains
glue; the extra predicates (orientation + sealing, mutex + mailboxes, joint
occupation of cells) need not. An unsat instance is **absence of a global
section of that constrained presheaf**, not a failure of the sheaf axiom for a
structure that is already a sheaf.

Where a 1-cocycle appears, it is ordinary Čech data with coefficients in a
tiny coefficient object (\(\mathbb{Z}/2\mathbb{Z}\) orientation, or a wait-for
graph). We do not invent a cohomology theory for reachability alone.

Recursive substitution: a parent context \(U\) contains a shaft / spawn /
inner frame \(V\). A local section of \(U\) includes a section of \(V\),
transported along the shaft, message, or nested accessibility relation.

Local-frame transformations (label opacity) are per tile type, per worker
name, or per frame — **not** independently at every unfolded occurrence,
unless a production slot says so. Maze `descend` names the child type, which
is occurrence-slot level at depth 1 (crypt vs pit), not per deep copy.

## Correspondence

| Concept | Maze | Distributed | Epistemic |
|---|---|---|---|
| Base | Nested tile copies | Worker chain | Product of nested worlds |
| Cover | Tiles and shaft overlaps | Each worker's program + shared mutex/mailboxes | Each agent's partition of the outer frame |
| Local configurations | Walks in one tile with orientation | Prefix of a worker program with local inbox/lock | A cell of \(\sim_a\) (and a pointed inner chain) |
| Restrictions | Trace on shaft rooms | Messages and lock tokens on the boundary | Forget distinctions the agent does not have |
| Compatibility | Same room, orientation, and sealing bit on the overlap | Matching send/recv payloads; mutex occupancy 0 or 1 | Chosen cells have nonempty intersection |
| Global section | A completing route with required orientation | A completing interleaving | A chain in every chosen cell, plus modal truth at `actual` |
| Obstruction | Unique simple path has holonomy 1; exit sealed until a child is solved | Wait-for cycle while holding the mutex | Two nonempty cells with empty intersection |
| Recursion | Shaft into `nesting["deeper"]` or shaft `child` | Spawn copies input to a child worker | `levels` chain; inner atoms absent if truncated |
| Frame change | Per-tile room relabelling | Per-worker renaming | Per-frame world relabelling |

## Worked obstruction, maze

Depth 1, `cyclic_unsat`, clean, transparent. Keep rooms `dock - a -b - c - door`
with \(a\to b\) flipped. Crypt `entry - hall - exit` has no flip. Exit of keep
is sealed until a descend/ascend. Every local tile has an entrance-to-exit
walk. Every simple global walk uses \(a\to b\) once, so orientation at `door`
is 1, not the required 0. XOR cancellation by walking the cycle twice is
forbidden: each edge in a copy is used at most once. Nested deeper copies use
`inner_keep` with **no** flip, so depth does not cancel the root cocycle.

Independent verifier: BFS on `(stack, room, orientation, cleared, used edges)`,
then edge-by-edge replay of the witness.

## Worked obstruction, distributed

Depth 1, `cyclic_unsat`. Root program
`[spawn, lock, recv:child, send:child, unlock]`. Leaf
`[lock, recv:parent, send:parent, unlock]`. Each program is locally well-typed.
With one mutex, whichever agent locks first waits for a message the other
cannot send without the lock. No completing interleaving. Tree regime replaces
this with `lock, compute, unlock, send` on the leaf and no handshake: SAT, and
the witness is a trace, not `(input+1)`.

Independent verifier: replay of the trace under FIFO mailboxes and mutex;
SAT decided by BFS on program counters, not by evaluating an arithmetic tree.

## Worked obstruction, epistemic

Outer worlds `{w0,w1,w2}`. Ann partition `{w0,w1}|{w2}`, Bob `{w0}|{w1,w2}`.
`p` holds only at `w0`. Actual chain starts at `w0`, so \(p\) is true, but
\(K_{\mathrm{ann}} p\) is false (Ann considers \(w1\)). Bundle `{ann: w2, bob: w0}`:
each cell is nonempty, intersection empty. That is the gluing obstruction.
Nested `q` lives only on inner frames; a depth-1 query about `q` is false
because the atom is absent. Flattening chains to an explicit Kripke model
agrees with the nested evaluator.

## Transfer hypotheses (not evidence)

Plausible shared skills: recursive decomposition, transporting a solution
across a renamed local frame, composing partial configurations, detecting
that pairwise-ok locals miss a global section.

Domain-specific: geometry and sealing (maze), causal mailboxes and mutexes
(distributed), modal quantification over observation classes (epistemic).

No model has been run. Passing the reference solvers shows the judges are
exact for the supported class.

## Limitations

- Maze holonomy is \(\mathbb{Z}/2\mathbb{Z}\) with simple-edge walks; it is not
  a general Čech complex.
- Distributed topology is a chain, not an arbitrary process network.
- Epistemic nesting is a product of small S5 frames, not full dynamic
  epistemic logic or common knowledge.
- Label opacity is per type/name/frame, not per unfolded occurrence.
- `recursive_gluing_discovery` remains a relation-composition control, not a
  maze/trace/modal witness.
