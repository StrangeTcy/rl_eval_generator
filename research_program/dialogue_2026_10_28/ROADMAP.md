# Research portfolio

The first implementation portfolio is **sequential diagnostic inquiry plus adaptive strategic communication**. These address a concrete gap between a static answer and an action that changes what is observed next. They extend existing T1, belief-inference, and signaling work without duplicating the recursive-gluing workstream.

All experiment specifications below are prospective. No new model performance has been measured. Exact opportunity IDs, source spans, quotations, and relationships are in `inventory.json`; the complete primary source is `source.md`.

## Priorities and scientific value

Scores are planning judgments on a 1–5 scale, not measurements. Priority also accounts for whether the target mechanism already has an adequate implementation.

| Work | Scientific value | Gap | Feasibility | Reuse | Decision and reason |
|---|---:|---:|---:|---:|---|
| Sequential diagnostic inquiry | 5 | 5 | 5 | 5 | Implement now: T1 cannot independently score an unperformed diagnostic or recovery trajectory. |
| Adaptive source inference and sender deployment | 5 | 5 | 4 | 5 | Implement now: static labels and supplied answer tables do not establish strategic adaptation. |
| Oracle/parser/seed/replay integrity | 5 | 5 | 5 | 5 | Implement with both: otherwise a putative effect could be a judge or information-boundary artifact. |
| Source-disagreement and truthful-subset selection laws | 5 | 4 | 3 | 5 | Next: add competing priors and explicit selection probabilities; preserve non-identifiability. |
| Private/public coordination topology | 5 | 4 | 3 | 4 | Extend existing S5 and type-game code; require the optimal policy to change across twins. |
| Hidden causal structure and intervention discovery | 5 | 4 | 3 | 4 | Next independent family: shared observable traces, different interventional predictions. |
| Memory interference | 4 | 5 | 2 | 3 | Defer until retention/context access is enforced by the runner. A complete transcript invalidates the intended restriction. |
| Recursive grammar and representation transfer | 5 | 3 | 3 | 4 | Coordinate with the active sibling; add independent non-gluing transfer only after its evidence contract stabilizes. |
| Literal reconstruction of exclusion-8x6 pilot | 3 | 3 | 2 | 3 | Defer: the log does not fix selection/observation timing and supplies no reproducible pilot artifacts. |
| Broader worldview disruption | 3 | 4 | 1 | 2 | Retain as a hypothesis; specify warranted revision and a dependency model before implementing. |

## Implemented family I: sequential diagnostic inquiry

Sources: OP015, OP025, OP028, OP035, OP039, OP040, OP043, OP059. Implementation: `arena/inquiry/diagnostic.py`, `finite.py`, `presenter.py`.

**Mechanism and task.** A hidden state has a known prior. The investigator chooses costly tests to minimize final classification loss plus cost. A presenter selects the order of all available experiment descriptions. All three binary partitions, probabilities, and costs remain fixed within presentation twins.

**Observations and actions.** Only requested outcomes are revealed. The actions are a permutation, `inspect`, and a terminal state/probability forecast. Early stopping is a meaningful action. Neither role sees the world seed, ground truth, or the oracle's action values.

**Generator.** Semantic seeds vary prior weights, costs, and the assignment of partitions to test IDs. Separate private seeds sample the hidden state. Budgets 1–3 and balanced/skewed prior regimes produce cost and horizon changes. The canonical structure is small and supplied; this is not latent grammar discovery.

**Judge.** A finite-horizon exact decision tree includes stopping, all remaining tests, and future observations. Regret is computed before the current result. Terminal decision loss, realized multiclass Brier, expected forecast excess, test cost, stopping regret, and choice regret remain separate.

**Rivals.** First-row following, cheapest-test selection, always stopping, and exhaustive decision-tree search. All tests have binary outcomes, so counting output symbols cannot identify the best partition. Enumeration is a valid reference strategy; success does not reject it as an explanation.

**Discriminating experiments.** Helpful/neutral/adversarial row orders under paired worlds; public-oracle invariance; fixed-schedule versus free-query mediation; cost reversal; prior reversal; budget sweep. An unchanged optimal policy on a given pair is a valid null, not a reason to relabel the case as a success.

**Evidence ceiling.** Appropriate query choice and calibrated inference in this finite task; paired behavioral presentation effects after randomized execution. No evidence of altered model parameters, internal attention, or general reasoning transfer.

## Implemented family II: adaptive strategic source

Sources: OP005, OP007, OP010, OP018, OP020, OP023, OP034, OP052, OP075. Implementation: `arena/inquiry/strategic.py` plus the deployment port in `session.py`.

**Mechanism and task.** A persistent source has private final quality and either a sincere or strategic disposition. Sincere reports follow fresh private noisy observations. Strategic recommendations maximize a payoff under an audit contract. The observer chooses audit rates within a fixed disclosed or blind visibility condition and forecasts disposition, quality, deliberate misleading recommendation, sincere error, and literal falsehood.

**Observations and actions.** Only the response to a chosen protocol is shown. The source sees the protocol in disclosed trials and believes the audit probability is zero in blind trials. An optional independent quality reveal is a recovery arm. A separate sender port gives the evaluated sender its own legitimate private quality and grades its report by payoff regret.

**Generator.** Semantic seeds vary priors, gain, and fine. Private seeds determine persistent source disposition, quality, and round-indexed sensor draws. Assertion/certificate twins share those variables; only literal statement semantics differ. Noise-zero cases supply accurate sincere controls. Repeated probes are legal because new sincere measurements can be informative.

**Judge.** The response law follows the declared payoff and noise contract. Exact four-state conditioning yields event probabilities. The observer's disposition decision loss/regret, query cost, proper scores, and expected forecast errors are separate from sender deployment regret. A positive report with a bad outcome is not automatically labeled deliberate: strategic and sincere-error causes can retain positive posterior probability.

**Rivals.** A stationary response model, indiscriminate suspicion, literal-truth-only classification, narrative-role heuristics, and fixed audit selection. The observer has a supplied model class, so it can enumerate it; this family measures model comparison and protocol planning, not unrestricted opponent-model invention.

**Discriminating experiments.** Announced versus hidden audit changes at the same realized source; payoff threshold reversals; assertion versus true certificate; repeated low/high protocol sequences; zero versus nonzero sincere error; matched pre/post quality reveal. Equilibrium claims are limited to the explicit one-decision sender response, not an unspecified multi-round Nash equilibrium.

**Evidence ceiling.** Public-information inference, payoff-sensitive response prediction, protocol planning, and detection/deployment separation. Different priors causing sincere disagreement and novel game structures remain unimplemented conditions.

## Expansion cards

Each card below is a proposal, not a renamed implemented family.

| Family | Formal object and interface | Generator and success certificate | Rival and decisive control |
|---|---|---|---|
| Truthful subset selection | Sender samples a true subset using a public conditional selection law; receiver observes subset and chooses an action. | Generate finite worlds with more than one true subset; compute posterior from content **and selection probability**. Score forecasts and action regret. | Content-only Bayes versus selection-aware Bayes; matching length or truthfulness alone must not erase the difference. |
| Sincere disagreement | Two observers have declared distinct priors or distinct evidence, with no strategic incentive. | Cross common/distinct prior and public/private evidence; certify when agreement is and is not entailed. | Always-deception detector versus calibrated uncertainty; do not misuse Aumann's theorem without common prior/common knowledge. |
| Coordination under information topology | Finite information partitions plus utilities; choose coordinate/safe action. | Same first-order marginals, changed disclosure reachability; retain only uniquely solved or set-valued correctly graded cases. | First-order-only policy and finite-depth approximations; best action must change under an independently checked topology intervention. |
| Hidden causal mechanism | A small structural causal model; passive observations followed by chosen interventions. | Generate graph twins with identical observational distributions and distinct intervention responses; hide coordinate mapping and hold out intervention combinations. | Correlation-only model, direct enumeration, and supplied-representation oracle; require held-out predictions or intervention certificates. |
| Hypothesis search | Hidden finite grammar, paid simulation/inspection, terminal program and predictions. | Separate grammar production holdouts from depth/seed holdouts; independent interpreter certifies outputs. | Template retrieval, expanded brute force, memorization, and invalid simplification; record compute budget and counterexamples. |
| Memory misdirection | Controlled event exposure, explicit retention boundary, distractors, delayed reconstruction. | Swap temporal order and distractor relevance while keeping target events fixed; exact reconstruction and downstream prediction. | Full-transcript retrieval control and no-distractor control; do not claim memory effects if unrestricted history is accessible. |
| Learner shaping | Explicit learner update state, teacher/adversary intervention, later held-out task. | Vary correct/incorrect learner model and objective; inspect the scripted update only where the engine owns it. | Stop-gradient, one-step greedy, and random interventions; test whether a supplied learning model adds value. |
| Cross-domain inquiry transfer | Independently generated frozen ML debugging and symbolic diagnostic tasks. | Preserve a query-value contract but change available tools, observations, and judge; evaluate held-out causes. | Surface-skin transfer is insufficient; compare an independently solved target domain and cap search/diagnostic cost. |

## Evidence sequence and next work

1. Execute the authored regressions in an authorized isolated runner; inspect independent-oracle disagreements before changing either oracle.
2. Add a deterministic multi-seed readiness sweep, recording every generated problem, rejected/invalid action, and reference/baseline trace. Reference agreement alone does not prove both implementations correct; retain the hand-derived fixtures.
3. Run a small, explicitly authorized infrastructure pilot with no capability headline. Examine every observation for leakage and every action for parser ambiguity.
4. Freeze a prospective design: target versions, parameter/rule holdouts, endpoint units, exclusions, pairing, replication, and equivalence margins. Randomize arm order. Never select seeds solely because a learned target exhibits the desired effect.
5. Estimate presentation effects and protocol adaptation separately. Resample at the semantic-case level with nested world/replication handling. Report excluded pairs and invalid rates alongside scored outcomes.
6. Add truthful selection laws and sincere disagreement, then the independent causal mechanism family. Extend recursive transfer in coordination with the sibling implementation rather than modifying its current files.

No step above authorizes provider calls, a local process, or publication. The execution prohibition remains in force for this delivery.
