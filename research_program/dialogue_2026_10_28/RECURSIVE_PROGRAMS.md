# Recursive rule discovery and composition

Status: source implemented; regression specifications authored; runtime and model performance unverified. This family adds a recursively composed task with hidden local semantics. It does not supply the recursive opponent modelling handled by the separate epistemic-control workstream, and it does not modify recursive-gluing.

## Source and scientific purpose

This is a concrete extension of OP019, candidate generation and search allocation (dialogue lines 585–594 and 4966–4968), and OP070, latent rule reconstruction with an independent non-gluing language (lines 1013–1038). OP029's warning that symbolic notation alone does not establish reasoning also applies. These opportunity references motivate a new experiment; the dialogue contains no performance result for this implementation.

The previous four-state diagnostic task supplied its full likelihood matrix. This environment instead supplies a family of possible interpreter rules and lets the agent acquire local input/output evidence. The same unknown local rules are reused at every node of larger expression trees. The evaluated agent must both infer local rules and calculate outputs of nested compositions.

## Formal task

There are one to three active opaque operators, `A`, `B`, and `C`. Each has a persistent hidden rule

`F(left,right) = (a*left + b*right + c) mod p`.

The modulus is 7 or 11. For each operator independently, `a` and `b` are uniform in `1..w`, and `c` is uniform in `0..w-1`, with `w` equal to 2 or 3. Therefore an operator has 8 or 27 candidate rules. Three operators at width 3 give 19,683 candidate grammars before observations. The syntax and affine family are known; the coefficients and their assignment to operator labels are hidden.

A probe applies one operator to two literal residues. Nested probes are forbidden. Optional initial demonstrations are also local: the first zero, one, or two members of the basis `(0,0), (1,0), (0,1)` per active operator. Probe results come from the trusted engine.

The agent sees three target expressions of exact depth 2–5. Every active operator appears at the root of at least one public target. All available evidence is depth one, so the target compositions have not appeared among examples or queries. The target output cannot be obtained by submitting the target as a query.

The terminal action supplies three output predictions and a local-rule certificate: one proposed coefficient triple per active operator. The engine separately evaluates that certificate on three unseen expressions at depth `public depth + 1`. The unseen expressions are never displayed or accepted as probes.

The certificate test measures whether the submitted local model extends correctly to new compositions. The engine performs those deeper evaluations, so it is not evidence that the evaluated agent itself calculated their outputs. Direct predictions on the public nested targets provide that separate behavioral requirement.

## Implemented difficulty axes

These are structural and information controls. Their effects on particular models have not been calibrated.

| Axis | Implemented values | What changes |
|---|---|---|
| Public recursive depth | 2, 3, 4, 5 | Number of nested operator applications along a root-to-leaf path. Private certificate transfer reaches depths 3–6. |
| Recursive branching | `chain`, `balanced` | A chain has `2d+1` expanded nodes; a balanced tree has `2^(d+1)-1`. Depth five therefore has 11 versus 63 nodes. |
| Repeated substructure | `distinct`, `repeated` | Repeated balanced trees reuse the same child at both positions. At depth five, the expanded tree has 63 nodes but only six distinct subtrees. This exposes a compression/memoization control. Repetition is inapplicable to the chain condition and rejected there. |
| Active operator count | 1, 2, 3 | Number of separately hidden local rules that must be distinguished and composed. Root coverage ensures each active operator is represented. |
| Local rule repertoire | Width 2 or 3 | Eight or 27 rules per operator; up to 19,683 grammar combinations. |
| Query budget | 0–9 | Amount of shallow evidence the agent may purchase with its query allowance. Repeated inputs are rejected. No monetary query cost or optimal-query regret is currently scored. |
| Initial evidence | 0–2 basis examples per operator | Changes identification burden while holding target depth and hidden rules fixed under the same seeds. |
| Arithmetic domain | Modulus 7 or 11 | Changes modular wraparound and the number of possible target outputs. This is an arithmetic condition, not an established monotone hardness scale. |

Semantic and private-rule seeds are separate. With zero initial demonstrations, changing only the private-rule seed changes neither the public target text nor the semantic identity. With demonstrations, displayed outputs appropriately depend on the hidden rules.

Depth is not sufficient to establish effective semantic difficulty. If every operator has `a=b=1`, flattening the expression into leaf and offset sums is valid. Terminal records therefore include the number of nonassociative operators, along with expanded node counts and distinct-subtree counts. Report results by those realized properties instead of treating every deep tree as equally demanding.

Changing tree shape or repetition also changes generated leaf/operator placements. Those switches are controlled generator conditions, not exact fact-preserving presentation twins. The hand-worked composition fixtures provide tightly matched controls; larger campaigns still need balanced sampling and explicit matching choices.

## Scoring and uncertainty

The judge enumerates the finite grammar posterior consistent with all public observations. Local probes factor by operator, permitting exact candidate filtering. The prior is uniform over those compatible assignments.

The metrics separate:

- Realized error on the three public target predictions.
- Expected prediction loss, the marginal Bayes risk, and prediction regret conditional on acquired evidence.
- Whether the submitted certificate contradicts any observation.
- Remaining candidate-grammar count and whether the evidence uniquely identifies the grammar.
- Direct composition errors relative to the submitted certificate.
- Realized certificate error on three unseen deeper programs.
- Certificate expected-loss excess over independent marginal predictions on those unseen programs.
- Probe count and the realized structural metadata.

The certificate excess comparator can choose each target output independently. It is a lower bound on the loss of a coherent single-model certificate, not the optimal coherent-certificate policy. Its metric name is `certificate_transfer_excess_vs_marginal_oracle`, not certificate-policy regret.

When the budget is insufficient, multiple grammars can remain compatible. A modal prediction can then be wrong in the sampled world while incurring zero posterior decision regret. A non-unique certificate is not treated as proof of faulty reasoning merely because it differs from the hidden assignment. Observation consistency, posterior ambiguity, and realized transfer remain separate outputs.

The current oracle conditions on the evidence the agent chose. It does not assign optimal sequential query regret. A policy can waste queries and still produce optimal final predictions; its query count and budget condition must be reported.

## Independent reference and rivals

The engine evaluates each expression by recursively reducing its children modulo `p` and applying the local rule.

The public reference imports neither `game.py` nor `semantics.py`. It parses the public contract and observations, enumerates compatible coefficient tuples independently, and evaluates targets by expanding path-weighted contributions. Each leaf contributes its value multiplied by the product of coefficients along its path; each internal offset contributes with the weight arriving at that node. Reduction modulo `p` occurs after that expansion.

Its probe policy gathers the three affine basis inputs per operator, omitting demonstrations already present. The identities `c=F(0,0)`, `a=F(1,0)-c`, and `b=F(0,1)-c` identify a local rule over these fields. This gives a guaranteed identifying strategy within three probes per operator, not a query-minimal strategy. At lower budgets, the reference returns posterior-mode predictions and a compatible certificate.

The shallow rival obtains the same local-rule evidence but replaces every internal child below the root by its first leaf. This isolates failure to compose from failure to identify local coefficients. The constant-output rival does not investigate. Enumeration and algebraic expansion remain valid solution methods and are not defeated shortcuts.

## Hand-derived controls

Take `p=7`, `A(x,y)=2x+y+1`, and `B(x,y)=x+2y`.

- `A(1,2)=5` and `B(3,4)=4`, so `A(A(1,2),B(3,4))=1`.
- Swapping those two complete subtrees gives `A(B(3,4),A(1,2))=0`. Leaf values and operator counts are preserved; their recursive arrangement changes the answer.
- The shallow rival gives 6 on the first expression despite being supplied the correct local coefficients.
- Repeated application `A(x,x)` starting at 1 gives `1 -> 4 -> 6 -> 5`. At depth three the expanded tree has 15 nodes and only four distinct subtrees.
- With width 2 and only `A(0,0)=1` observed, four local rules remain. The nested expression `A(A(0,0),A(0,0))` has outputs `3,4,4,5` under those rules. Its modal answer has irreducible error one half.
- With `A(x,y)=x+y`, flattening is valid. Rebracketing four leaves preserves their sum modulo seven. That is a necessary positive control for the claim that a structural manipulation should change a decision.

These are mathematical fixtures, not executed environment results.

## Files and interfaces

The source modules are `arena/recursive_programs/semantics.py`, `game.py`, `reference.py`, `session.py`, `__init__.py`, and `__main__.py`. `tests/test_recursive_programs.py` contains 30 authored test methods. No existing core, registry, provider, campaign, or recursive-gluing file was edited.

Controller initialization has the format:

`recursive SEMANTIC_SEED PRIVATE_RULE_SEED DEPTH OPERATORS WIDTH BUDGET SHAPE SHARING DEMONSTRATIONS MODULUS`.

The text session allows at most 24 responses; invalid actions consume the response allowance but leave game state intact. EOF and exhausted retries remain unscored. Replay accepts valid actions and reconstructs observations and metrics from private controller configuration. Configuration and private seeds must not be supplied to the evaluated agent.

In-process trials are for trusted scripted policies. They are not a process-isolation boundary. No external-process launcher, provider adapter, or ordinary patching-registry entry is supplied.

## Readiness and interpretation limits

No imports, compilation, regression tests, episodes, model calls, or provider campaigns were executed. Static inspection is not runtime validation. The parent `arena` package imports provider support using `datetime.UTC`, requiring Python 3.11 or newer. Focused `unittest` discovery in an authorized isolated checkout avoids the repository's existing pytest campaign-completion hook.

Before model use, run the authored tests and cross-check all allowed local rules on the hand-derived expressions. Sweep depths, branching, repetition, operator counts, repertoire widths, evidence budgets, demonstrations, moduli, and independent rule seeds. Preserve disagreements between the reduction engine and path-expansion reference. The maximum partially observed case enumerates 19,683 grammars over six target trees; its latency remains unmeasured and must be checked before a campaign.

Success would support local rule identification within the declared affine family and correct evaluation of new recursive compositions. It would not establish discovery of arbitrary grammars, general program synthesis, novel operator-family transfer, an internal recursive algorithm, recursive social modelling, or cross-domain intelligence. Fresh coefficient assignments and deeper trees are distinct holdouts; they are not a new mathematical language.
