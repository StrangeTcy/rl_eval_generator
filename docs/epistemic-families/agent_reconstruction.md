# Agent reconstruction

`arena/epistemic_families/agent_reconstruction.mjs` implements finite reconstruction of a strategic agent. The unknown variable is a preference-and-belief hierarchy, sampled from a published weighted catalogue. It remains fixed throughout the episode. The solver buys diagnostic executions and then identifies a catalogue model and forecasts the agent's action in a separate payoff game.

The catalogue contains executable minds, not query-response tables. Every public context contains two state-dependent payoff matrices. A mind has subjective state weights, weights on its own and the other player's utilities, and a base distribution over the other player's actions. Nested `belief` records alternate player roles. Each nested record executes its own best response using its own subjective information and objective. Its action becomes the parent mind's predicted opponent action. The root then computes its own best response. Exact rational utility comparison and lowest-index tie breaking make the result deterministic.

The deepest mind uses its base opponent distribution. A root with no nested record is a nonrecursive subjective expected-utility agent. One and two nested records execute distinct levels of opponent reasoning. Neither queries nor answers change the target mind.

## Independent axes

Each axis accepts `easy`, `medium`, or `hard`, independently of the others. Omitted axes use `easy`. Seeds are safe integers.

| Axis | Easy | Medium | Hard | Operative change |
| --- | --- | --- | --- | --- |
| `models` | 3 | 5 | 7 | Candidate preference and belief hierarchies |
| `recursion` | 0 | 1 | 2 | Nested opponent models executed beneath the target |
| `actions` | 2 | 3 | 4 | Actions per player, payoff matrix dimensions, and forecast dimension |
| `visibility` | action and margin | action | action parity | Information retained in each diagnostic observation |
| `budget` | 4 | 2 | 1 | Maximum paid diagnostic executions |

The visibility margin is the target's selected subjective expected utility minus its highest alternative expected utility. Parity coarsens actions modulo two. With two actions, parity preserves the full action signal; its information loss becomes visible when the action axis introduces more alternatives. Budget pressure is independently applicable at any catalogue size or recursion depth. These are substantive task parameters, not a promise that every generated seed is monotonically harder at every level.

## Public interaction

```javascript
const game = create({ seed: 19, privateSeed: 5,
  axes: { recursion: 'hard', visibility: 'medium' } });
const observation = game.submit(reference(game.view()));
```

`view()` returns cloned JSON containing `family`, `phase`, resolved `axes`, the executable `models`, generated `queries`, `targetContext`, query `history`, `budget`, `rules`, and `actionSchema`. Model priors are positive integer weights. Context action labels are in index order. Payoffs have shape `[state][player0Action][player1Action][player]`.

The source law is an exact uniform finite ticket population of size `sum(priorWeight)`. Each model occupies its weight in tickets. `abs(privateSeed) % sum(priorWeight)` selects a ticket deterministically; a complete uniform ticket cycle reproduces the declared prior exactly. A fixed seed replays a selected target and does not itself constitute a random sample from that prior.

Actions are closed objects:

```javascript
{ kind: 'query', query: 'q0' }
{ kind: 'answer', decision: 'm1',
  modelForecast: ['1/4', '3/4', '0'],
  actionForecast: ['1/4', '3/4'] }
```

A query costs one unit, can be used once, and returns only its identifier, retained diagnostic signal, and cost. `q0` through `q3` are generated payoff games. `null` is an executable all-zero payoff game. Signals from `null` are identical across all models. Queries consume no random state and cannot alter the target or future payoffs.

Forecasts are exact nonnegative fraction strings, ordered as the public model catalogue and held-out action labels, respectively, and each vector sums to one. Every position must be explicitly populated, including zero probabilities; sparse native arrays and null JSON entries are rejected. Answers require a valid model decision. Malformed fields, extra fields, invalid fractions, repeated queries, and queries beyond budget throw before mutation. After a terminal answer, further actions throw. Mutating a returned public packet has no effect on the game.

## Inference and scores

The public solver executes each candidate on queried contexts and removes those inconsistent with the retained signals. Remaining prior weights normalize to the exact posterior. Held-out action probabilities sum that posterior over the independently executed target-context actions. No held-out target response is exposed before terminal submission.

The query planner exhaustively considers every affordable unused query and every reachable observation partition, with memoized finite-horizon recursion. Its objective is query cost plus twelve times model-identification error probability. Equal values favor immediate stopping. Query regret sums conditional Bellman action gaps; final decision regret adds the submitted decision loss minus the optimal continuation value. This quantity is nonnegative and is zero on every reference-policy path. It is not the realized loss from the privately sampled target.

Terminal `metrics` are exact fraction strings:

- `regret`: accumulated planning and model-decision regret.
- `modelForecastExcess` and `actionForecastExcess`: squared distance from the public conditional posterior and held-out action distribution.
- `realizedModelBrier` and `realizedActionBrier`: separately reported Brier losses against the private target.
- `queryCost` and `remainingSupport`: resource use and posterior ambiguity.
- `score`: `1 / (1 + regret + modelForecastExcess + actionForecastExcess)`; `exact` is one precisely when score equals one.

An exact answer can retain substantial uncertainty. It need not identify the private target correctly in an ambiguous episode. A trusted `audit()` supplies the hidden model, target posterior, recursive held-out execution trace, observations, and terminal record. This audit is separate from solver-facing packets and is not an admissible reference input.

## Controls and evidence

`stop` submits the current exact posterior without inspecting. `null_query` wastes one query on the uninformative context. `certainty` asserts the first model with probability one. `no_recursion` collapses every root belief and performs inference under that ablation; if its false execution model assigns zero likelihood to history, it falls back to its unconditioned prior. This fallback is documented behavior of the ablation, not the reference.

Every seed divisible by thirteen makes all diagnostic matrices zero while retaining a separately generated held-out matrix. This fixture demonstrates that indistinguishable evidence does not justify certainty about preferences or future actions.

`node --test tests/epistemic_families/agent_reconstruction.test.mjs` covers independent hand calculations of subjective utility and two levels of recursive role switching, an exact one-query Bellman calculation, all 243 axis combinations, null/ambiguous contexts, private-target isolation, seeded payoff variation, strict parser behavior including sparse native forecasts, atomic errors, exact ticket-population counts, and executable baselines. The family supports bounded catalogue reconstruction and recursive best-response forecasting. It does not establish unrestricted social reasoning or inference about natural-language agents.
