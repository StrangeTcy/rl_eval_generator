# Belief revision in a finite dependency graph

This family evaluates whether corrected evidence produces the warranted changes
in conclusions while preserving conclusions supported elsewhere. Its answers
are consequences of an explicit logical graph and public evidence, not a hidden
list of nodes to keep or delete.

Root propositions are independent fair binary variables before observations.
Literal nodes test a stated value of a proposition, and higher nodes combine
them with AND or OR. Initial observations support the generated conclusions.
A correction packet replaces some observed premise values and withdraws others.
Replacement supersedes an old observation; withdrawal creates uncertainty.
Unchanged evidence retains its force.

## Axes

| Axis | Easy | Medium | Hard | Operative effect |
|---|---:|---:|---:|---|
| `premises` | 8 | 10 | 12 | Changes the number of propositions, observations, and graph literals. |
| `depth` | 1 | 3 | 5 | Changes the number of dependency layers below corrected premises. |
| `supports` | 1 | 2 | 3 | Changes the redundant conclusion's independent support branches. |
| `corrections` | 1 | 2 | 3 | Changes the number of premise replacements and affected chains. |
| `uncertainty` | 0 | 1 | 2 | Withdraws observations, leaving respectively 1, 2, or 4 compatible worlds. |

All combinations retain enough distinct unaffected propositions for the
alternative branches and the dependency guards. An alternative supporting
literal does not occur in the corrected branch's guard set. Greater redundancy
can make a conclusion easier to preserve; levels are not a universal difficulty
ordering. AND chains can simplify algebraically, so depth is not evidence that
recursive computation is necessary.

## Interface and verification

`create({seed, privateSeed, axes})` creates an episode. The first public view
contains the graph, proposition order, original evidence, and a notice that
corrected evidence is pending. The policy requests `{kind: "receive_correction"}`.
The response supplies the replacement and withdrawal operations. Terminal
answers before this step are rejected.

After correction, the policy submits
`{kind: "submit", predictions: [{nodeId, probability, status, witnesses}, ...]}`.
Every target must occur once. `status` is `entailed`, `refuted`, or `undetermined`.
Each undetermined conclusion needs two complete assignment bitstrings in the
public proposition order: one makes it true and one makes it false. The scorer
checks compatibility with corrected evidence and evaluates the graph on those
assignments. Definite conclusions require no witnesses.

The independent root prior and public evidence define the probability of every
compatible world. The scorer enumerates those worlds and verifies universal or
existential consequences. The private realized assignment is used only for
realized forecast loss. It is absent from public views and correction packets.
The trusted `audit()` must stay outside the policy interface.

## Measurements and controls

Forecast excess, realized binary Brier loss, status accuracy, and semantic
certificate validity are separate metrics. Correction-propagation accuracy is
reported on conclusions whose probability changed. Retained-support accuracy
is reported on previously certain conclusions that remain certain and true.
Both subsets include their counts; a rate of one for an empty subset is vacuous
and must not be presented as observed success.

The public reference enumerates compatible worlds, returns the exact posterior
and statuses, and supplies uncertainty witnesses. The stale-evidence baseline
uses superseded observations. The global-disbelief baseline rejects every
conclusion. These fail different obligations: updating affected conclusions
and retaining independently supported conclusions.

## Validation and limits

Tests include a hand-derived three-proposition example, an independently coded
full truth table, every axis level, combined boundary configurations,
independent-support structure, hidden-assignment invariance, state-preserving
input rejection, and semantically incorrect witness rejection. The initial
execution passed **9/9 tests**. The shared study saves final source hashes and
execution artifacts separately.

The current graph grammar is deliberately finite and narrow. It tests explicit
logical consequence revision under trusted corrections. It does not identify an
LLM's internal belief state, measure general worldview change, or treat all
revision as damage. Ordinary forward evaluation and truth-table enumeration
remain valid complete solutions. New graph grammars and causal models would
require separate validation and structural holdouts.

Implementation: `arena/epistemic_families/belief_revision.mjs`.
Tests: `tests/epistemic_families/belief_revision.test.mjs`.
