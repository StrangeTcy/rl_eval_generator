# Inquiry after controlled retention

The policy first sees a finite history of independent binary events. Advancing
replaces that view with a structural event skeleton, a value-independent subset
of retained records, and a limited retrieval budget. Each policy call receives
only the current view. The controller keeps the exposure and audit separate.

| Axis | Easy | Medium | Hard | Effect |
|---|---|---|---|---|
| `events` | 4 | 6 | 8 | Number of original event values. |
| `sources` | 1 | 2 | 3 | Number of interleaved sources. |
| `retention` | 4 | 2 | 1 | Original records available after advancing, capped by event count. |
| `task` | Last value | Last per source | Parity per source | Defines the target event subsets. |
| `retrievals` | 2 | 1 | 0 | Additional original values available for purchase. |
| `distractors` | 0 | 2 | 5 | Irrelevant current events, with no change to the posterior. |

Targets are XORs of their listed original values. An unknown independent bit
makes the target posterior exactly one half. Known targets have posterior zero
or one. The reference enumerates affordable retrieval subsets and minimizes
mean posterior decision loss plus `1/20` per retrieval. It can stop without
spending the entire budget, including when a partial parity retrieval is useless.

Actions are `advance`, `retrieve` with an original event ID, and `answer` with
one probability and binary decision per target. Probabilities use exact
nonnegative fractions. Invalid, duplicate, retained, and unaffordable retrievals
are rejected without changing the current view.

Forecast excess and decision regret measure reasoning relative to the available
information. Realized Brier loss, realized decision loss, irreducible risk, and
retrieval cost remain separate. A calibrated reference can incur positive
realized loss and irreducible risk. Campaign controls require zero forecast
excess and zero decision regret; they do not turn uncertainty into a failure.

The tests cover all 729 axis combinations, private-ticket calibration,
retention independence, retrieval planning, distractor invariance, and malformed
actions. Pairwise campaign execution additionally saves replayable evidence.
Level names describe interventions and do not establish measured difficulty.
This family measures behavior under a controlled context boundary; it does not
identify internal model memory or provide hostile-code process confinement.

Implementation: `arena/epistemic_families/memory_inquiry.mjs`.
Tests: `tests/epistemic_families/memory_inquiry.test.mjs`.
