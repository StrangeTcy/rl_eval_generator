# Truthful selection and prior disagreement, 2026-11-09

A new finite inference task implements the roadmap's **truthful subset selection**
and **sincere disagreement** expansion cards. Its 63-case structural study scored
126 scripted answers and replayed every public packet, answer and score. Fourteen
regressions passed, including an independent enumeration of concrete selection
tickets for all 63 cases.

## Implemented behavior

`arena/inquiry/selection_laws.mjs` accepts two to eight worlds, positive integer
prior weights, up to sixteen message truth masks, world-specific selection
weights and an observed message. It rejects any positive selection weight on a
false message, empty selection laws and impossible observations. The message
selection weights are normalized separately in each world before conditioning.

The public task states the complete finite model. A submission chooses a world
and supplies exact posterior fractions. The judge returns expected multiclass
Brier loss, optimal Brier risk, excess forecast loss, expected decision loss and
decision regret separately. Tied optimal decisions receive zero regret. Invalid
answers leave the task open; a valid answer closes it. There is no sampled hidden
world: these scores are exact conditional expectations under the stated law.

The generator's two worlds can be read as the true fact sets `{common, left}` and
`{common, right}`. The three messages reveal `{common}`, `{common, left}` or
`{common, right}`. The displayed message is always `{common}`. Its literal content
and truth conditions remain fixed across the paired selection-law conditions.
The likelihood of selecting it changes, so its evidential meaning changes.

The independent-prior conditions disclose prior weights `2:1` and `1:2` to two
observers with the same evidence and selection law. They supply no strategic
incentive and make no inference of dishonesty from posterior disagreement.

## Executed structural controls

The prospective grid contains severities 2–8, three selection laws and three
prior regimes. Both supplied-law Bayes and a content-only Bayes baseline answer
every case. No case was excluded or selected based on the observed effect.

| Check | Result |
|---|---:|
| New Node regressions | 14 passed, 0 failed, 0 skipped |
| Independent ticket-enumerator comparisons | 63/63 agree |
| Saved and replayed answers | 126/126 |
| Selection-law pairs with a changed optimal decision | 20/21 |
| Distinct-prior pairs with different posteriors | 21/21 |
| Informative cases with nonzero content-only forecast excess | 42/42 |
| Informative cases with nonzero content-only decision regret | 19/42 |
| Uninformative cases with zero content-only forecast excess and decision regret | 21/21 |

The single pair without a decision reversal retains a tied optimum; it is a
valid null and is retained. The posterior still changes. Disagreement need not
imply a different decision: probabilities and decision regret remain separate.

A hand-derived severity-nine fixture, outside the saved grid, gives posterior
`9/10, 1/10` versus `1/10, 9/10` for the same true message under opposite laws.
Content-only Bayes retains `1/2, 1/2`: expected Brier loss is `1/2`, optimal risk
is `9/50`, and excess is `8/25`. In the second law the default decision has regret
`4/5`. At the first law, distinct `2:1` and `1:2` priors produce posteriors
`18/19, 1/19` and `9/11, 2/11`.

## Reproducible commands and evidence

Run in Anaconda Prompt, from the repository root:

```bat
conda activate epi-comp
node --test --test-reporter=tap tests/test_truthful_selection.mjs
node tools/truthful_selection_study.mjs show 9 favors-1 common
node tools/truthful_selection_study.mjs score 9 favors-1 common "answer 1 1/10 9/10"
node tools/truthful_selection_study.mjs run NEW_OUTPUT_DIRECTORY
node tools/truthful_selection_study.mjs replay NEW_OUTPUT_DIRECTORY
```

The run command refuses to overwrite an existing directory. It writes the full
design and source hashes before scoring, then saves all public packets, answers,
scores and a checksum. Replay regenerates and compares the complete record; a
test changes a score and recomputes its checksum to verify that semantic replay
still rejects it. Checksums are integrity checks rather than signatures.

Saved evidence is in
[`runtime_validation/truthful-selection-20261109-final/`](runtime_validation/truthful-selection-20261109-final/).
The adjacent
[`truthful-selection-20261109-final-summary.json`](runtime_validation/truthful-selection-20261109-final-summary.json)
contains exact aggregate fractions. The execution manifest records commands,
exit codes, source/test/log hashes and Node v24.19.0. The established Anaconda
`epi-comp` activation was used; no Python executable discovery or dependency
installation was needed.

The earlier `truthful-selection-20261109` directory retains the first 13-test
development run. The final run adds a regression for exact posteriors with more
than six-digit denominators and raises the bounded fraction grammar to 128
digits, covering the general finite specification. Current replay uses the
final directory because source identity is pinned.

## Provenance and limits

This is a self-authored extension of the roadmap's explicit expansion cards and
the dialogue's OP007 (“Selection policies are evidence”) and OP023 (“Truthful
subset versus falsehood versus instruction”). The source snapshot and original
opportunity records remain intact. A new supplemental evidence record describes
the increment; neither opportunity is promoted from partial to complete.

These are deterministic checks of supplied finite probability laws. They do not
measure a learned model, unknown-law discovery, free-form framing, multi-round
interaction, recursive learner changes, or the separate false-message and
instruction conditions. Fixed priors differing after shared evidence do not
establish a violation of any common-prior agreement theorem. The finite task is
available through its public JSON view, strict answer interface and CLI; it is
not registered as a generated patching environment or integrated into provider
campaigns. Existing Python games and `core.py` were not edited.

The next bounded extension is to elicit answers from an independent external
policy using only the public packet, retain its raw replies, and replay the same
score records. Unknown selection-law inference requires a separately specified
observation and identifiability contract.
