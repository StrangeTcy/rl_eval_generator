# Epistemic reasoning environment

`epistemic_reasoning` is a direct-answer family of deterministic, finite tasks. It is generated with the repository's `generate_env.py` pipeline and seed-aware renderer. The learner receives `prompt.md`, public `task.json`, a schema-shaped `answer.py`, and format-only `visible_tests.py`; the answer key remains in the judge image. The judge re-derives the complete instance from its variant, size, and seed before grading.

The implementation carries accepted components from `StrangeTcy/epistemic-compiler` commit `cdd03a2365174250d32b89d970be85bae21c7998`. The source checkout was kept separate. The retained CS001–CS012 unittest suite has 84 passing cases; CS004, CS006, CS008, CS010, and CS012 are regression-test blocks, not extra inference implementations. CS013 E6 was implemented with the user's approved choices and committed as `ea9e11d`. CS014's tests-only behavior-preservation block was committed separately as `1de48b2`; CS015 onward remain unprocessed.

## Generate and run

```sh
python generate_env.py --env epistemic_reasoning --list-axes
python generate_env.py --env epistemic_reasoning \
  --name epistemic_event_42 --difficulty event_sparse,compact --seed 42
cd epistemic_event_42
./run_eval.sh
```

The first difficulty axis selects a task variant; the second selects `compact` or `expanded` finite data. Seeds use a local `random.Random(seed)` instance, so identical variant, size, and seed produce identical public task and judge oracle. No model/API call or training is used.

## Supported task variants

| Variant | Learner task and oracle contract |
|---|---|
| `event_sparse` | Exact named-event update; absent prior-world likelihoods mean zero and out-of-model entries are ignored. |
| `event_strict` | Exact named-event update; likelihood keys must exactly cover the prior worlds. |
| `policy_sparse` | Update from complete normalized observation rows; missing row labels mean zero, and this is not an event-only likelihood vector. |
| `policy_strict` | Update from normalized rows that explicitly cover exactly the declared observation alphabet, including zeros. |
| `relational_modal` | Universal knowledge over the listed general relation edges. Relations are not silently closed to S5; an empty outgoing set is vacuously true. |
| `s5_knowledge` | Callable proposition/knowledge evaluation over validated S5 partitions. The oracle also cross-checks the separate partition-based S5 interface. |
| `announcement_unpointed` | Sequential public restriction without an actual-world truth check; later formulas are reevaluated in the updated model. The source operation rejects a restriction that eliminates every world. |
| `announcement_checked` | Sequential restriction with a truth check at the supplied actual world at every prefix. A false-at-actual step is rejected; the task adapter represents that rejection as `accepted: false` with no final model. |
| `deterministic_silence` | Exact posterior from deterministic Boolean rules; silence means no rule fires, and every rule is evaluated. |
| `silence_empty_protocol` | An empty protocol guarantees silence, leaving the prior unchanged. |
| `common_knowledge` | Callable common knowledge using full finite reachability closure over the union of selected partitions. |
| `common_knowledge_empty_group` | The accepted empty-group convention: the closure contains only the starting world. |
| `information_pool` | Individual information set and pooled information as the intersection of selected agents' cells. |
| `information_empty_group` | Individual information plus the full-world-set result for an empty pooled group. |
| `pure_bne` | Complete finite pure-strategy Bayesian-Nash equilibrium set under an exact common prior and callable exact-rational utilities adapted from an explicit payoff table; empty and multiple sets are both represented, mixed equilibria are out of scope. |

## Serialization and grading

Probabilities and utility payoffs are serialized as reduced `numerator/denominator` strings (including `0/1`), then decoded to `fractions.Fraction`; floats and decimal strings are rejected. For `pure_bne`, type profiles are ordered JSON arrays aligned with the declared agent order and become tuple keys internally, never delimiter-joined strings. The complete payoff table is validated and snapshotted behind the preserved callable utility interface. The exact public callable-formula interfaces remain in the copied accepted modules. The task adapter uses an explicit JSON AST with only `atom`, `neg`, and `knows` nodes; it constructs the accepted callables rather than replacing them with string-evaluated formulas. Adapter equivalence is tested against direct callable construction.

The answer is parsed from one literal `ANSWER = {...}` assignment and never executed. Configured `check_fraction` scoring uses two checks—schema validity and exact oracle equality—plus the target's required-file anti-gaming cap. `visible_tests.py` validates answer shape only and does not reveal the expected result.

## Limits and non-claims

- Instances are finite symbolic tasks (world-based variants currently use 3–8 worlds; pure-BNE games use 2 or 3 types per agent and 2 actions), not empirical evaluations of a learned agent. Pure-strategy enumeration rejects games with more than 20,000 joint pure-strategy profiles.
- The BNE task asks only for the complete pure-strategy set; it neither computes mixed equilibria nor asserts uniqueness when multiple pure equilibria exist.
- Silence protocols are deterministic. No support for probabilistic-agent rules, and no independence assumption between agents is claimed.
- Pooled information is set intersection only; it does not implement communication and is not common knowledge.
- General relational accessibility and validated S5 partitions remain separate interfaces.
- The JSON formula grammar is an explicit finite adapter, not a serializer for arbitrary Python callbacks.
- The target integrates CS001–CS013, with CS014 represented by separate behavior-preservation regression tests only. CS015 onward remain unprocessed. This does not cover the full v3 proposal or broader research portfolio, and passing tests is not evidence of scientific validity.

## Accepted-source mapping

| Source block | Target implementation | Retained/regression and integration tests |
|---|---|---|
| CS001 | `files/event_bayes.py`; `task_engine.py` exact-rational event adapters and sparse/strict variants | `tests/epistemic_source/test_event_bayes.py`, `test_source_e1_fixtures.py`; `tests/test_epistemic_reasoning.py` |
| CS002 | `files/epistemic_relations.py`; general-relation and partition-based S5 variants in `task_engine.py` | `test_epistemic_relations.py`; adapter/integration tests |
| CS003 | `files/supplied_policy.py`; separate sparse and strict policy variants | `test_supplied_policy.py`; adapter/integration tests |
| CS004 | No new inference implementation; accepted E1 test fixtures retained unchanged | `test_source_e1_fixtures.py` |
| CS005 | `files/public_announcements.py`; explicit formula JSON adapter and both announcement variants | `test_public_announcements.py`; `test_source_e2_fixtures.py`; formula-adapter/integration tests |
| CS006 | No new inference implementation; accepted E2 test fixtures retained unchanged | `test_source_e2_fixtures.py` |
| CS007 | `files/silence.py`; deterministic protocol adapter and two silence variants | `test_silence.py`; `test_source_e3_fixtures.py`; adapter/integration tests |
| CS008 | No new inference implementation; accepted E3 test fixtures retained unchanged | `test_source_e3_fixtures.py` |
| CS009 | `files/common_knowledge.py`; nonempty- and empty-group variants | `test_common_knowledge.py`; `test_source_e4_fixtures.py`; integration tests |
| CS010 | No new inference implementation; accepted E4 test fixtures retained unchanged | `test_source_e4_fixtures.py` |
| CS011 | `files/fragmented_observation.py`; individual and pooled-information variants | `test_fragmented_observation.py`; integration tests |
| CS012 | Distinct four-world crossed-partition regression and eager rejection of overlapping S5 cells; no new inference implementation | `tests/epistemic_source/test_source_e5_fixtures.py` |
| CS013 | `files/bayesian_games.py`; exact common-prior finite pure-BNE enumeration and JSON payoff-table adapter | `tests/epistemic_source/test_cs013_finite_bne.py`; generated-environment tests in `tests/test_epistemic_reasoning.py` |
| CS014 (tests only) | Separate regression fixtures for multiple coordination equilibria and common-prior normalization | `tests/epistemic_source/test_cs014_bne_fixtures.py` |
