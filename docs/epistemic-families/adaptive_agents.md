# Adaptive agents

This bounded family asks for forecasts of a learner after external training updates. The evaluator executes integer state transitions over a generated input stream. Inspecting a checkpoint reveals an observation of the hidden learner; it never changes the training inputs, learner state, update schedule, or future actions. There is no teaching action.

## Public and private information

The public packet contains possible initial scores and polarities, positive integer prior weights, the external input stream, update law, regime schedule, decision threshold, historical checkpoint identifiers, observation rule, and remaining inspection budget. It contains no realized learner identity or future target action. The separate trusted `audit()` record includes that identity and its executed trajectory.

The historical prefix contains six updates. Future inputs are also declared: the uncertainty is which learner received them, not an undisclosed random input. Each diagnostic is usable once. The null diagnostic always returns `withheld`. Seeds divisible by 17 explicitly declare a diagnostic outage, so every diagnostic is uninformative.

The source law is an exact uniform finite ticket population of size `sum(priorWeight)`, with each learner occupying its weight in tickets. `abs(privateSeed) % sum(priorWeight)` deterministically selects a ticket. A uniform complete ticket cycle realizes the published prior; fixing one seed replays one learner rather than drawing a random learner.

## Independent axes

| Axis | Easy | Medium | Hard | Executable change |
| --- | --- | --- | --- | --- |
| `learner_count` | 2 | 4 | 6 | Candidate initial states, polarities, and prior support |
| `update_law` | cumulative | leaky | window-two | State transition operator |
| `change_cadence` | 0 | 3 | 1 | Fixed regime or external polarity reversal every N updates |
| `observation_access` | state and action | action only | action only at alternate checkpoints | Information returned by inspection |
| `forecast_horizon` | 1 | 2 | 4 | Future transitions and number of required forecasts |
| `inspection_budget` | 3 | 2 | 1 | Number of permitted inspections |

The difficulty labels define controlled contrasts, not a theorem that every generated instance becomes harder monotonically. A window can erase initial-state uncertainty, and a forecast may be identifiable without identifying the learner. All 729 axis combinations are executable and tested.

The threshold and external input stream are initialized separately from variable-size catalogue generation. Changing only the forecast horizon extends the same stream: it preserves the threshold, learner definitions, historical observations, and all existing future action prefixes. It changes the number of requested forecasts and can change which diagnostic best serves that longer objective.

## Dynamics and exact reference

At update index `t`, the external regime multiplier is `(-1)^floor(t/cadence)` when cadence is positive; it is one otherwise. The update is the input times that multiplier times the learner's polarity. Cumulative learning adds it to the previous score. Leaky learning adds it to the previous score divided by two and truncated toward zero. Window learning sums the two most recent updates; the initial score begins as a one-entry window. The post-update action is one exactly when score meets the public threshold.

The public reference replays every candidate's transitions, conditions its prior on the diagnostic history, and computes exact rational probabilities for each future action. An exhaustive memoized finite-horizon planner chooses inspections to minimize expected mean binary Brier loss. It stops when further inspection cannot improve that objective. It does not access `audit()`, closures, or the hidden learner.

For an independent hand example, learners with zero initial score and polarities `+1/-1`, prior weights `1:3`, cumulative updates `[2,-3,4,-1]`, threshold zero, and two historical steps yield future positive-action probabilities `1/4,1/4`. The mean Bayes risk is `3/16`. Inspecting either historical action identifies polarity and reduces the future risk to zero; a null inspection retains `3/16`. With stream `[0,1]` and one historical step, both historical actions are one and the future remains ambiguous.

## Interface and scoring

`create({seed, privateSeed, axes})` defaults unspecified axes to easy. Submit either `{kind:'inspect', query:'checkpoint_0'}` or `{kind:'forecast', probabilities:['1/4', ...]}`. Probabilities must be exact nonnegative fraction strings in `[0,1]`, one per future checkpoint. Every array position must be explicitly populated; sparse native arrays and null JSON entries fail validation. Forecast submission terminates the episode. Unsupported fields, malformed fractions, repeats, and unaffordable actions fail before mutation.

`forecastExcess` is mean squared distance from the exact conditional forecast. `inquiryRegret` accumulates each inspection's Bellman gap plus the gap from stopping. `brier` is the realized mean squared forecast error; `conditionalBayesRisk` reports irreducible residual uncertainty. `score = 1 / (1 + forecastExcess + inquiryRegret)`. A calibrated reference can score one while realized Brier loss remains positive in ambiguous cases. `remainingSupport` and `inspections` describe the final information state and resource use. Rational metrics are serialized as strings.

Baselines stop immediately, spend an inspection on the null diagnostic, or forecast persistence of the most recent action while ignoring upcoming updates. Tests cover hand-derived trajectories and information values, observational ambiguity, public/private isolation, immutable external trajectories, malformed and sparse actions, generated variation, preserved action prefixes across horizons, exact ticket-population counts, all axis combinations, and a changing-learner contrast where the frozen-state baseline loses forecast accuracy. These controls establish bounded learner forecasting, not open-ended adaptation ability.
