# Recursive delegation

This finite environment asks a principal to inspect a hierarchy, issue a numeric mandate, and predict the output returned by a recursive delegation program. The program contains 2–40 participants, six possible states, and three possible outputs. Participants have individual execution costs, signed objective offsets, private signals, and upstream/downstream positions.

The entry point is `arena/epistemic_families/recursive_delegation.mjs`. It exports `definition`, `create`, `reference`, `baselines`, and the independently inspectable `execute` and `signal` operations. `create({seed, privateSeed, axes})` returns `view()`, `submit(action)`, `done`, and trusted `audit()`. Omitted axis levels are `easy`.

## Independent axes

| Axis | Easy | Medium | Hard | Executable change |
|---|---|---|---|---|
| `depth` | 1 | 2 | 3 | Maximum number of recursive delegation edges; new interior participants receive upstream mandates and issue downstream mandates. |
| `branching` | 1 | 2 | 3 | Number of children available to each non-leaf; each child admits three downstream commands. |
| `alignment` | 0 | 1 | 2 | Magnitude of signed participant objective offsets, applied before clamping the ideal output to 0–2. |
| `private_information` | Full state | Shifted pairs | Erased | The participant's signal partition and the result of inspecting its signal. Pair boundaries depend on individual channel offsets. |
| `inspection_budget` | 2 | 1 | 0 | Maximum number of paid, distinct inspections before final delegation. |

Every axis can be set independently. Increasing depth or branching changes an executable tree, rather than an attached difficulty label. Increasing alignment changes participant payoffs; it does not guarantee lower performance on every episode. Resource and information controls also admit easy episodes and ties. All 243 combinations are tested.

## Participant program

An episode's public packet contains the six possible principal goals and their prior weights, the complete hierarchy, each participant's preference offset and local execution costs, the signal rule, and the utility coefficients. The sampled state and realized participant signals are private.

A participant receives a command in `{0,1,2}`. It chooses among:

1. Execute an output locally, with its own output-specific cost.
2. Select a child, send that child any of the three commands, and pay one transaction-cost unit.

It minimizes its expected loss:

`2 × (clamp(state.goal + participant.bias, 0, 2) − returnedOutput)²`

`+ 3 × (incomingCommand − returnedOutput)² + transactionCost`.

The participant conditions the published prior on **its own signal**. A delegation alternative is evaluated by recursively executing that child's policy in each state in the parent's signal cell. The realized child output returns through the selected path. A policy cache stores choices, not realized outputs: a child may distinguish states that its parent cannot distinguish. Local alternatives precede child alternatives; child and command order break exact ties.

This is a specified local-belief protocol. Received commands affect utility and are not treated as evidence about the sender's signal. The model does not claim Bayesian equilibrium inference over strategically selected messages. Principal inspections are private to the principal and never update or train participants.

Tree shape and participant costs are generated from seed and axes. The implementation computes behavior from the recursion and utilities; there is no supplied answer matrix. The public `execute` operation permits independent examination of hypothetical states without access to the game's sampled state.

## Actions and observations

`{kind:'inspect', participant:'p0'}` buys an available participant signal for one cost unit and consumes one budget unit. Available inspections include the root, representative extreme leaves, and the constant `null` channel. An inspection is usable once. The returned observation contains only its participant id, signal, and cost.

`{kind:'delegate', request:1, forecast:['0','1/2','1/2']}` sends a final request to the root and predicts the returned output. Forecast entries are bounded nonnegative exact fraction strings, in output order 0, 1, 2, summing to one. Every position must be explicitly populated; sparse native arrays and null JSON entries are rejected. Actions use closed schemas. Malformed forecasts, unknown ids, duplicate inspections, exhausted budgets, and submissions after termination throw without changing public or trusted state. Completed forecasts are copied into the trusted record, so changing submitted or returned arrays cannot rewrite an audit.

The public view is a fresh JSON-compatible copy. `privateSeed` selects a prior-weighted state and does not affect the initial public packet. Only trusted `audit()` exposes the selected state and, after submission, the selected execution path, each private signal, each upstream/downstream command, and each local expected loss.

The prior is an exact uniform finite ticket population of size `sum(priorWeights)`, assigning each state its published weight in tickets. Selection uses `abs(privateSeed) % sum(priorWeights)`. Enumerating a complete uniform ticket cycle reproduces the weights exactly; an individual fixed seed is deterministic replay rather than a random prior draw.

## Reference and scoring

The reference consumes only the public packet. It executes the finite participant program in each possible state, filters states using purchased observations, and solves the inspection decision tree exactly using rational arithmetic. It either buys an inspection with strictly better expected value or stops and issues a request minimizing expected principal loss.

The principal's terminal loss is `12 × (state.goal − returnedOutput)²`. Inspection costs and expected principal loss jointly define the sequential planning objective. At each visited decision, `regret` accumulates the gap between the chosen action's optimal continuation value and the best available continuation value. This is a nonnegative sum of conditional decision regrets along the observed path, not a realized-loss difference from a counterfactual episode.

`forecastExcess` is the sum of squared differences between the submitted output distribution and the exact posterior predictive distribution for the submitted command. `score = 1 / (1 + regret + forecastExcess)`. The exact reference therefore scores one even when the hierarchy has irreducible disagreement or information loss. `expectedPrincipalLoss`, `inspectionCost`, `remainingSupport`, `realizedOutput`, `realizedDepth`, and `realizedPrincipalLoss` remain separately visible, so normalized optimality is not confused with successful goal attainment.

## Controls and validation

`no_inspection` directly delegates with exact public prediction. `assume_compliance` predicts that every final output equals the principal's requested output. `flatten_tree` removes the root's children in its internal model. The latter two can fail on fixed fixtures, exposing sensitivity to participant incentives and recursive structure.

An erased-signal episode retains all six states. The `null` inspection never conveys state information. Seed multiples of 13 make every state's principal goal one, producing a control where inspecting cannot improve the decision and incurs exactly one regret unit per wasted inspection.

Run `node --test tests/epistemic_families/recursive_delegation.test.mjs`. Tests include a hand-derived two-participant payoff calculation; an independent uncached integer-weight recursion; a three-edge route with interior nodes occupying both relational roles; a hand-derived inspection value; conditioning after a coarse signal; null and ambiguity controls; sparse forecast rejection; action atomicity and snapshot isolation; completed-input isolation; exact ticket-population counts; inspection noninterference; and every one of the 243 axis combinations. This validates the published finite task, not open-ended delegation competence.
