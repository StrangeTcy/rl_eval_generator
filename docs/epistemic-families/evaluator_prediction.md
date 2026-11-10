# Evaluator prediction and revision

This family asks for candidate-specific score forecasts while a target evaluator
remains unavailable. It is a finite synthetic document task, with no safety-filter
or human-persuasion component. Every possible rubric is declared. The hidden
quantity is which rubric is active.

The source is a small catalog of binary facts. Candidate reports contain claims
about those facts and optional caveat/example sections. The evaluator's criteria
are measured from each report: accuracy, coverage, concision, and optionally the
two section indicators. Its score is a positive weighted mean in `[0,1]`.
Independent factual quality is the mean of accuracy and coverage. A report can
improve on the target rubric without producing an equal improvement in factual
quality; neither metric substitutes for the other.

## Axes

Each axis changes generated data or the legal interaction, and can be combined
with all levels of the other axes.

| Axis | Easy | Medium | Hard | Operative effect |
|---|---:|---:|---:|---|
| `criteria` | 3 | 4 | 5 | Adds evaluator criteria and available document features. |
| `rubrics` | 2 | 4 | 6 | Adds distinct possible weight vectors. |
| `candidates` | 2 | 4 | 6 | Adds reports whose forecasts and selection must be considered. |
| `revisions` | 0 | 1 | 2 | Expands the allowed edit sequence. |
| `uncertainty` | 9 | 3 | 1 | Sets prior weight on rubric 0; other rubrics each have weight 1. |

The labels are configuration levels, not a proof of monotone difficulty.
Additional revisions provide resources as well as a larger planning problem.

## Interface

`create({seed, privateSeed, axes})` creates an episode. `view()` returns source
facts, current reports, possible rubrics and prior probabilities, permitted
edits, remaining revision budget, and the full public rules. The selected rubric
and private seed are omitted. `audit()` is a trusted recording interface and
must never be passed to a policy.

An edit is
`{kind: "revise", candidateId, editId, predictedBefore, predictedAfter}`.
The two candidate-specific score forecasts are recorded before the edit is
applied. Edits correct a false claim,
add missing factual coverage, remove repeated claims, or add an available
section. The response contains only the revised report and remaining budget.
There is no target feedback during revision.

Terminal submission is
`{kind: "submit", selectedId, predictions: [{candidateId, score}, ...]}`.
It must forecast every current report once. Malformed actions are rejected
without changing episode state. A terminal result closes the episode.

The public reference policy exhaustively plans up to the permitted two edits
to maximize the best posterior expected rubric score, then selects that report
and forecasts posterior mean scores. It uses only the public view. Baselines
make no edits, select by factual quality, or pretend the first rubric is certain.

## Measurements

- All-candidate realized and conditional forecast MSE.
- Forecast excess above the posterior-mean optimum.
- Selected-candidate forecast MSE and excess, retained separately from the
  all-candidate measurements.
- Expected and realized evaluator selection regret among the final reports.
- Selected report's independently measured factual quality and quality regret.
- Number of revisions used.
- Prospective before/after revision-forecast errors, with their observation count.

The MSE of posterior-mean forecasts can remain positive because the target
rubric is unknown. That uncertainty is different from forecast excess. MSE and
selection-conditional errors are calibration diagnostics; one episode cannot
establish population calibration. Regret is among the reports present at the
end, not a claim of universal optimality over arbitrary documents.

## Validation and limits

The family tests hand-derived accuracy/coverage/rubric scores, all levels of all
five axes, hidden-state invariance of public packets, absence of target feedback,
atomic invalid actions, distinct normalized rubric alternatives, uncertainty,
and public-policy completion at multiple seeds and combined levels. The initial
execution passed **9/9 tests**. The shared study saves final source hashes and
execution artifacts separately.

This measures explicit finite evaluator modelling and revision decisions. It
does not establish that an LLM internally simulates another evaluator, that a
real external judge has been identified, or that performance generalizes to new
rubric structures. Expected-utility enumeration is a legitimate baseline.
Target information is intentionally unavailable until terminal submission;
trusted in-process objects are not an operating-system sandbox.

Implementation: `arena/epistemic_families/evaluator_prediction.mjs`.
Tests: `tests/epistemic_families/evaluator_prediction.test.mjs`.
