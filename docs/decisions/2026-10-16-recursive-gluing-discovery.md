# Recursive gluing discovery: compact grammar, not an expanded CSP

Date: 2026-10-16. Status: implemented as `recursive_gluing_discovery`.
Control: `recursive_gluing` v0 (commit `93cc8dc`) remains the fully expanded CSP.

## Hypothesis

A model that recovers the reusable interface of a recursively defined constraint
grammar can answer from a description whose size does not grow with the unfolded
occurrence count \(2^{d+1}-1\). That is a claim about *representation*, and about
what a future model evaluation might show. It is not a claim that the expanded
CSP is computationally infeasible at the current hard axis.

Measured compact-vs-expanded sizes and runtimes are in
`2026-10-16-recursive-gluing-scaling.md`. On this implementation the expanded
solver still materializes and decides d=12 (hard axis) in about a second; d=15
is expensive in memory and time; d=24 was not materialized.

Correct answers are not proof of discovery. No model has been run. Three
*later* experimental conditions are named only as a design split, not as
completed arms:

1. ordinary explicit CSP on a materialised unfolding (v0 / expand-baseline);
2. a solver given canonical integer coordinates (not implemented as a distinct
   solver; `arm_given_canonical` currently aliases the compact oracle);
3. a solver that must work from type-local frames and the compact grammar.

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
  Implemented as a **per-module-type** relabelling. Stem occurrences share one
  domain. Per-occurrence / per-rule opacity is a remaining limitation, not a
  current axis.

## What this does not claim

No model has been run. Passing the compact reference solver shows the instrument
is exactly checkable, not that a model discovered the transducer. Exponential
occurrence counts do not by themselves imply exponential expanded runtime; see
the scaling report.
