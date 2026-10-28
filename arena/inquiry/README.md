# Observable inquiry games

Status: implemented source and authored regression suite; **not executed or campaign-ready**. The mission prohibits local commands and tests. No isolated Python runner is available through the current tools.

This package adds two interactive mechanisms beside the existing Arena tracks. It uses ordinary classes, tuples, exact fractions, bounded recursive decision trees, and a closed text protocol. It changes no `core.py`, provider code, registry entry, or recursive-gluing file. These are specialized interactive games, not generated patching tasks; adding them to `envs/registry.yaml` would misrepresent their interface.

## Diagnostic inquiry

`Diagnostic` generates a prior over four hidden states, three deterministic binary tests, and independent test costs. A semantic seed determines the public problem; a private world seed samples the hidden state from that prior. Budgets are 1, 2, or 3. The balanced and skewed prior generators are different parameter regimes, not distinct latent grammars.

A presenter can permute all three experiment descriptions. It cannot supply prose, delete a fact, change a cost, or see the world seed. An investigator requests test outcomes one at a time and submits a state decision and probability vector. Early answers are legal. Costs and remaining budget can make stopping optimal. Tests cannot be repeated.

`InquiryPlan` computes exact finite-horizon Bayes decision risk. Every inquiry regret is the selected action's expected remaining loss minus the best available remaining loss, **before** revealing the outcome. Stopping and final decision regret are separate fields; early stopping never receives a fabricated zero inquiry score. These values have decision-loss units, not bits. They are not the log's proposed entropy-only metric.

`TwoRoleTrial` supplies only public text to the presenter and investigator. `FirstRowPresenter` provides helpful and adversarial controls against the explicitly assumed `FirstRow` investigator. It optimizes first-query regret under that opponent model. This is a constructed positive control, not evidence that a learned presenter can model an unknown opponent.

## Strategic source and deployment

`StrategicSource` has a persistent hidden pair: final quality (bad/good) and source disposition (sincere/strategic). A sincere source sees a fresh noisy private signal each round. A strategic source sees final quality and chooses whether to recommend acceptance from explicit payoffs. The evaluator knows the prior and contract, not the realized pair.

For a bad case, recommending has expected payoff `(1-audit_probability)*gain - audit_probability*fine`; declining pays zero. Good cases yield `gain` when recommended. Ties decline. A disclosed protocol changes the source's audit belief. A blind protocol leaves that belief at zero. Protocol queries therefore intervene on the response law rather than merely relabeling a transcript. Contract settlement occurs outside the observation channel: no unrecorded audit result is supplied to either participant between queries.

The assertion channel recommends with “the final check passed.” The certificate channel recommends with the true statement “the precheck passed,” while concealing final quality when it is bad. These are distinct literal-truth conditions under the same action incentives. A positive recommendation can arise from sincere sensor error or deliberate selective communication; the judge scores posterior event probabilities instead of demanding an unknowable hidden label.

`Sender` and `SenderSession` expose a separate deployment task. The sender receives its own private quality and selects a report. Deployment regret is scored against its payoff contract. It is never pooled with the observer's detection or forecasting scores.

The observer's disposition decision is strategic at `p_strategic >= 1/2` and sincere otherwise. Its realized decision loss, posterior decision regret, and accumulated protocol cost are separate metrics. This makes an always-distrust policy pay for confident misclassification even when it avoids every query.

An optional `reveal` supplies independent final quality after a report. It is a separately flagged recovery intervention. Compare a pre-reveal forecast from a matched clone with the post-reveal forecast; the default episode does not force intermediate belief elicitation. The query objective concerns source disposition, so quality-reveal arms must be analyzed separately from ordinary inquiry trials.

## Interfaces

The controller, outside the evaluated agent, owns configuration and private seeds. Once an isolated runner is available, its entry point is `python -m arena.inquiry`. No command has been run for this delivery.

Controller initialization, supplied before attaching the evaluated agent:

```text
diagnostic 13 29 2 balanced
```

The first role supplies a presentation, then the investigator supplies actions:

```text
present 2 0 1
inspect 0
answer 0 1/4 1/4 1/4 1/4
```

The example is a protocol illustration, not a reference solution. The final line intentionally need not be correct.

Source-game initialization and example actions:

```text
source 11 27 2 disclosed certificate
protocol 0
protocol 2
answer 1/2 1/2 1/4 1/4 0
```

A source answer contains `p_strategic p_bad p_intentional p_error p_literal_false`. Intentional and error events concern the latest positive recommendation on bad quality. No positive recommendation means those events are absent. Report 0 declines and makes no factual quality claim. Certificate claims are always literally true.

All probability tokens are bounded exact nonnegative fractions. Source noise denominators are at most 8, keeping exact posteriors within the action grammar's six-digit numerator/denominator bounds at the supported horizons. Unknown commands, additional prose, duplicate diagnostic tests, impossible budgets, nonfinite values, and post-terminal actions are rejected. Invalid actions do not mutate game state. The transport has a 12-response limit; EOF and exhausted retries are unscored statuses.

Terminal output is JSON encoding a tuple of named records. Metric collections are ordered `(name, value)` pairs, not one aggregate score. Fraction values are strings. The public stream excludes configuration, private seed, oracle action values, posterior targets, and realized hidden state until explicitly revealed or scored.

`Trial(configuration, policy).run()` is the offline API for trusted scripted policies. `policy.act(observation)` receives public text only. `PublicOracle` parses those observations and independently solves decision trees with **unnormalized** branch weights; it imports neither engine nor `finite.py`. `Replay(configuration).consume(action_tuple)` reconstructs outcomes and metrics, rejecting incomplete and appended transcripts. Records preserve public observations, raw responses, errors, transitions, and valid actions in order. Replay establishes score reproducibility, not that a recorded policy generated its actions independently.

No in-process Python object is an OS security boundary. Untrusted evaluated code must run in another process/container controlled by an authorized runner; it must not share the trusted engine's Python address space or controller initialization stream. The present package contains no launcher, provider integration, credential handling, or automatic campaign.

## Validation and limits

`tests/test_inquiry_games.py` contains hand-derived rational fixtures, action/parser attacks, hidden-seed view invariance, cost/horizon and stopping checks, uncertain-cause examples, protocol counterfactuals, replay rejection, independent public-oracle trials, and two-role controls. None has been executed here.

For future isolated validation, use Python 3.11 or newer and focused standard-library discovery: `python -m unittest discover -s tests -p test_inquiry_games.py -v`. The Python floor comes from the inherited `arena` package import of `datetime.UTC` in provider support. That parent import also constructs an HTTP opener and credential-path candidates; source inspection found no top-level provider call or credential-file load. The repository's existing pytest completion hook can dispatch campaigns in CI, so the focused `unittest` route is intentional. See [the readiness record](../../research_program/dialogue_2026_10_28/READINESS.md) for these source findings and all outstanding execution gates.

Existing exact Bayes and presentation modules were inspected. Their general mapping-based contracts and single-answer measurement interface do not provide a sequential game under the current coding constraints. This package therefore shares a narrowly bounded four-state experiment calculus between its two mechanisms. It does not replace the existing epistemic semantics or T1 contract.

The diagnostic matrix is supplied. The source's candidate decision laws are supplied through a payoff and noise model. Solving these finite games establishes neither hidden grammar discovery nor rejection of enumeration. Seed and parameter holdouts establish parameter generalization only. The research plan separately specifies new-rule, topology, source-disagreement, memory, and cross-domain tests that are not implemented here.
