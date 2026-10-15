# Recursive gluing discovery: compact grammar, not an expanded CSP

Date: 2026-10-16. Status: implemented as `recursive_gluing_discovery`.
Control: `recursive_gluing` v0 (commit `93cc8dc`) remains the fully expanded CSP.

## Hypothesis

A model that recovers the reusable interface of a recursively defined constraint
grammar can solve instances whose unfolded occurrence count is exponential in
the description size. A generic expanded CSP solver cannot, except on shallow
instances that this environment keeps as a cross-check, not as the task.

Correct answers are not proof of discovery. The environment makes structure-aware
computation useful and separates three later experimental conditions:

1. ordinary explicit CSP on a materialised unfolding (v0 / expand-baseline);
2. a solver given canonical integer coordinates;
3. a solver that must work from opaque type-local frames and the compact grammar.

## Formal class

A grammar G = (modules, productions, root, depth, closing) over a finite
interface alphabet of size q (prime, 3/5/7):

- Each module type has two ports, `enter` and `leave`, with a finite local
  label set of size q.
- A leaf type lists the allowed (enter, leave) pairs. In the supported class
  this relation is a translation in hidden coordinates: leave = enter + δ
  (mod q), presented only as a pair table.
- A branch type `stem` expands into a left and a right child. Three transport
  tables of size q wire `parent.enter → left.enter`, `left.leave → right.enter`,
  `right.leave → parent.leave`. Serial composition is the only combinator.
- The same productions apply at every remaining depth > 1 (both children are
  stems). At remaining depth 1 both children are leaves (`tip`, or `tip` and
  `weed` under the decoy axis).
- Optional root closing: an extra nonempty relation on the root (enter, leave).
  Tree regime: no closing. Cyclic SAT: identity closing with leaf δ = 0.
  Cyclic UNSAT: identity closing with leaf δ = 1. Because q is odd, 2^d ≇ 0
  (mod q), so the net translation of 2^d leaves cannot meet the identity.
  Every leaf table and every transport remains a nonempty bijection.

The unfolded semantics is a complete binary tree of 2^{d+1}−1 occurrences.
The compact description size is Θ(q²) pair tables, independent of d.

## Compact certificate

```
{"status": "sat"|"unsat",
 "realizable": {type: {depth_str: [[enter, leave], ...]}}}
```

`realizable[t][k]` is the set of interface pairs a module of type t can realise
with remaining depth k. Its size is O(|types| · d · q²), not O(2^d).

The judge recomputes the unique bottom-up summary independently. The candidate
must match it exactly. Status must be `sat` iff the root summary intersects the
closing relation (or is nonempty, in the tree regime).

## Oracle completeness

Let S(t, k) be the set of realisable (enter, leave) pairs.

- S(leaf, 0) = the listed leaf pairs.
- S(stem, k) = {(E, L) | ∃ a left pair and a right pair whose ports match E and
  L after the three transport tables}.

This is the inductive definition of the unfolded serial composition, so it is
sound and complete for the supported grammar. The step is O(q⁴) per depth and
does not materialise occurrences. A timeout is a judge failure, never unsat.

On depths ≤ 4 an independent expanded CSP (one enter/leave variable pair per
occurrence, the same wirings) is solved by AC-3 + backtracking and must agree
on satisfiability and on the root pair set.

## Competing explanations the design can distinguish

- Expanded search / full materialisation: input stays compact; occurrence count
  grows as 2^{d+1}−1. Tests report both sizes and refuse to expand hard depths.
- "Copy the leaf table upward": works only for identity transports and δ = 0;
  fails unsat closing, decoy leaves, and twisted mid-wire transports.
- Canonical integer coordinates: a test-only given-latent arm. The agent-facing
  instance never includes them.
- Treating decoy `weed` as `tip`: declared task change (`structural_ambiguity`).
- Label permutation: presentation change (`label_opacity`); answer preserved.

## What this does not claim

No model has been run. Passing the compact reference solver shows the instrument
is exactly checkable, not that a model discovered the transducer.
