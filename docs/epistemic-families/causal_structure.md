# Discover a causal structure

An episode shows several binary variables moving together. The investigator
chooses which variable to force to zero, observes the resulting distribution,
constructs a graph, and predicts what happens when two variables are forced at
once. The same initial observations fit different causal graphs. Successful
predictions therefore require learning which variables influence which others.

This develops the causal-structure portion of the original hypothesis-discovery
proposal. The existing `hypothesis_discovery` family constructs polynomial
expressions; this family constructs directed graphs. The earlier distinction
between discovering a world mechanism and identifying an evidence-selection
process is recorded in the
[source review](../research-review-2026-11-09/epistemic-source-opportunities.md).

## Generative contract

The hidden system is a rooted, labeled tree with three to five observed binary
variables. The root is an independent fair bit. Every other variable copies or
inverts its parent's value. Each edge has a binary `flip` parameter. This is a
deliberately small structural-equation grammar, with no hidden confounders,
measurement noise, cycles, or multi-parent mechanisms.

The initial observation is the exact joint distribution: two complementary bit
strings, each with probability one half. These observations determine relative
parities but do not identify the tree. All admissible rooted trees with those
parities have the same initial public packet for a fixed public seed and axes.
The prior is uniform over the finite admissible signed-tree support. A private
ticket selects an element modulo the support size; uniform-prior experiments
must sample tickets uniformly over that support, rather than treating a short
range of seeds as representative coverage.

A permitted experiment forces one variable to zero, cutting its incoming edge,
and returns the complete exact joint distribution. It costs one credit and
cannot be repeated. A clamp overrides the ordinary equation, including at the
root. Variables outside the clamp's descendants retain their ordinary causes.
The root remains random unless clamped.

Held-out targets clamp every unordered pair of variables to the mixed settings
`(0,1)` and `(1,0)`. Those combined interventions cannot be purchased as
experiments. Their predictions require composing the learned mechanisms and
respecting both cuts. The five-variable setting has twenty targets.

## Difficulty axes

| Axis | Easy | Medium | Hard |
|---|---|---|---|
| `node_count` | 3 variables | 4 variables | 5 variables |
| `max_children` | 1 child per node | At most 2 | At most 4 |
| `intervention_access` | Every variable | First half, rounded up | No experiments |
| `experiment_budget` | One credit per variable | Half that, rounded up | One credit |

Public variable labels depend on the public seed, independently of the hidden graph.
These settings alter the model class, access contract, or available resources;
their names do not establish an empirical model-performance ordering. With
three variables, the two larger branching bounds coincide. With no experiment
access, extra credits cannot change the evidence. These interactions are
explicit controls. At five variables the branching bounds admit 120, 540, and
625 rooted structures respectively, before relative parities are selected.

## Submission and scoring

The policy submits a graph with a root and `from`, `to`, and `flip` on each edge,
an `identified` or `ambiguous` claim, and an exact sparse outcome distribution for
every target. Assignments use the public variable order. No candidate graph
menu or hidden graph identifier is supplied.

Any graph consistent with the available evidence is a valid representative.
Graph identification is assessed over the surviving complete structures;
agreement on a particular forecast does not prove that the graph is identified.
Forecasters average over all compatible structures and the remaining root
randomness. Intrinsic randomness and unresolved structure can both contribute
to prediction uncertainty.

The scorer records graph-fit errors, identification errors, forecast excess
above the posterior mean, residual predictive uncertainty, experiments used,
and whether an affordable informative experiment was left unused. Expected
Brier loss is the sum of residual uncertainty and forecast excess. Predictive
score is one minus half that loss, averaged over held-out targets. The primary
score also penalizes graph-fit errors, identification errors, and premature
stopping. A calibrated but uncertain answer can have perfect reporting quality
and a predictive score below one.

Residual uncertainty is decomposed into intrinsic root randomness and
uncertainty about causal structure. In the three-variable unrestricted case
with all variables observed moving together, before any experiment these are
respectively `1/6` and `1/3`, giving total
Brier risk `1/2` and predictive score `3/4`. Once the graph is identified,
structural uncertainty is zero but intrinsic risk remains `1/6`; the predictive
score is therefore `11/12`.

The reference selects a diagnostic greedily by expected predictive-risk
reduction, with remaining structural ambiguity breaking ties. It does not claim
globally optimal query planning. Scores do not estimate full planning regret.

## Independence and controls

The controller enumerates trees using Prüfer sequences and evaluates structural
equations by forward propagation. The public reference enumerates parent
assignments and evaluates each variable by walking its ancestors to a clamp or
the root. It receives the same public packet as an external policy. These
implementations share the published grammar and fraction arithmetic, but not
tree enumeration or intervention evaluation.

Controls include hand-calculated observational twins with different intervention
responses, exact counts of admissible trees, all three-variable signed trees,
calibrated answers with no experiment access, premature submission, unsupported
certainty, malformed graphs, and combined interventions. The pairwise matrix
checks interactions between all four axes. Replay checks retain the complete
controller record separately from policy-visible data.

This establishes a bounded causal-discovery instrument. It does not establish
arbitrary causal discovery, human causal reasoning, or model performance. The
exact-distribution interface removes finite-sample estimation as a source of
difficulty.

## Run and integration

From the repository root, using Node.js 24:

```sh
node tools/epistemic_families.mjs validate-config envs/epistemic_families/causal_structure.yaml
node tools/epistemic_families.mjs show causal_structure --config envs/epistemic_families/causal_structure.yaml
node tools/epistemic_families.mjs run causal_structure --config envs/epistemic_families/causal_structure.yaml --output causal-structure-run
node tools/epistemic_families.mjs replay causal-structure-run
```

The output directory must be new. The family is registered with the shared
launcher and provider-free GitHub validation workflow. The existing Mercury and
Atria campaign profiles retain their original nine-family cohort. Enrolling
this extension requires a new campaign design; old checkpoints continue at
their saved source revision.
