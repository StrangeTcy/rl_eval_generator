# Construct a symbolic law

`arena/epistemic_families/hypothesis_discovery.mjs` requires construction of an executable expression. The learner receives a bounded grammar, experiment inputs, and an experiment budget. It never receives a menu of candidate models. Hidden laws are integer polynomials under a uniform prior over all canonical coefficient vectors within the published bounds, including the zero polynomial. A private finite ticket indexes the `(2 * bound + 1)^(degree + 1)` laws modulo that support size. The trusted audit records this ticket count, while the public view contains the support rule only. The public seed rotates the experiment-input order.

The four axes are maximum degree (1, 2, 3), coefficient magnitude (1, 2, 3), experiment budget (6, 4, 2), and accessible input domain (`[-3,-2,-1,0,1,2,3]`, `[-1,0,1]`, `[0]`). Each changes the support, permitted experiments, or available resources. A single observation may identify a low-degree law because the coefficient bound is informative. Input restriction to zero leaves every nonconstant coefficient unresolved, regardless of surplus budget.

An experiment is `{kind:"experiment",x:0}`. A final action has `kind:"submit_model"`, an executable `model`, `identification:"identified"` or `"ambiguous"`, and one posterior-predictive distribution per public evaluation input. Expressions use exactly these forms:

```json
{"op":"x"}
{"op":"const","value":1}
{"op":"add","left":{"op":"x"},"right":{"op":"const","value":1}}
{"op":"mul","left":{"op":"x"},"right":{"op":"x"}}
```

Expressions have at most 63 nodes and depth 12. Constants and final canonical coefficients obey the coefficient bound. Trailing zero coefficients are removed before each semantic degree check; the zero polynomial is represented by constant zero. Intermediate semantic polynomial degrees obey the degree bound. Consequently `(0*x)*x` and `(x + (-1*x))*x` are accepted as degree-zero expressions even with a degree-one bound. There is no dynamic evaluation or arbitrary function execution. AST validation expands coefficients with exact integer arithmetic. A separate recursive AST interpreter checks its outputs, while hidden laws are evaluated by Horner's method. Algebraically equivalent syntax within the bounded grammar is accepted.

A prediction has the form `{x:2,distribution:[{value:-2,probability:"1/3"},{value:0,probability:"1/3"},{value:2,probability:"1/3"}]}`. Its probabilities must be normalized exact fractions. Every evaluation input needs a distribution; sparse support is allowed. A representative expression need only belong to the class compatible with the observed experiments when the law is unidentified. Its predictions must still acknowledge the other compatible laws.

Reporting and discovery quality have separate scores. `reportingScore` is `1/(1 + observed model errors + identification error + observed forecast excess + unobserved forecast excess)`. The `exact` metric indicates zero reporting loss, including when a calibrated report retains uncertainty. `finalPredictiveRisk` is the posterior Bayes Brier uncertainty averaged over the fixed evaluation inputs. `expectedPredictiveBrier` adds average forecast excess to that risk, and the proper `predictiveScore` is `1 - expectedPredictiveBrier/2`. The primary `score` divides `predictiveScore` by `1 + observed model errors + identification error + premature-stop indicator`. Two perfectly calibrated reports can therefore receive different discovery scores because one acquired more predictive information.

`domainIrreduciblePredictiveRisk` is the posterior-expected risk after learning the outputs at every accessible experiment input, ignoring the experiment budget. It is a lower bound imposed by the input-domain restriction; `remainingReduciblePredictiveRisk` is the difference from current risk. Budget limitations can leave additional uncertainty. These quantities are not reporting errors or reasoning regret. The reference enumerates the bounded coefficient support internally, chooses experiments minimizing expected remaining support size, and constructs a Horner-form AST. This is a query heuristic, with no claim of optimal full-horizon query planning. Hidden-law agreement over the evaluation domain is reported separately and does not require the representative expression to equal the hidden law in an unidentified class.

For degree one and coefficient bound one, observing `f(0)=0` with only input zero available leaves `-x`, `0`, and `x` equally likely. At input two their outputs are `-2`, `0`, and `2`, each with probability `1/3`. Correct reporting scores one; its irreducible predictive risk is `4/7` and its primary score is `5/7`. A certain zero forecast has held-out squared excess `2/3` despite fitting the observation, reducing its primary score to `3/7`.

The query-quality regression uses degree three, coefficient bound three, a two-experiment budget, public seed one, and private ticket 1200 (the zero polynomial). Probes at zero and one leave 37 laws: `c0=0` and `c1=-c2-c3`. Independent counting of that coefficient lattice gives predictive risk `6334/9583` and score `6416/9583`. Probes at three and minus three identify the zero law and score one with zero risk. Both reports have reporting score one and zero forecast excess. The restricted-input, zero-law, semantic-degree, all-81-axis-combination, malformed-action, and state-preservation controls are also tested.

The bounded claim is symbolic construction and extrapolative uncertainty within a small published polynomial grammar. The family does not establish open-ended scientific discovery, invention of a grammar, or identification beyond available interventions.

Run `node --test tests/epistemic_families/hypothesis_discovery.test.mjs` from the repository root.
