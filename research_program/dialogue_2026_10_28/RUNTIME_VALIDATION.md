# Hosted runtime validation of the 28 covered ideas

Run [40714553198](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/40714553198) executed **109 tests: 109 passed, 0 failed, 0 skipped** on GitHub-hosted Ubuntu with Python 3.11.17. The tested commit is `6c8e94c4fee0593930194fc056e28f5647dd05f1`. No repository Python or test suite was executed on the user's machine. No model/provider call was made.

The inventory contains **15 source-implemented entries, 13 partial entries and 49 absent experiments**. All 28 covered entries now have passing evidence for their explicitly bounded implemented behaviors. Their missing experiments remain missing. OP037 remains absent: hidden-profile probing is not the accurate/wrong/absent opponent-model comparison.

## Commands and actual outcomes

Commands ran from the checked-out repository root on the hosted runner. Focused standard-library discovery avoids the repository pytest completion hook. No package installation was needed.

| Suite | Command | Passed | Failed | Skipped | Seconds | Raw evidence |
|---|---|---:|---:|---:|---:|---|
| epistemic-control | `python -m unittest discover -s tests -p "test_epistemic_control*.py" -v` | 23 | 0 | 0 | 0.048 | [log](runtime_validation/run-40714553198/op-validation-epistemic-control/unittest.txt) |
| inquiry | `python -m unittest discover -s tests -p "test_inquiry*.py" -v` | 48 | 0 | 0 | 0.106 | [log](runtime_validation/run-40714553198/op-validation-inquiry/unittest.txt) |
| recursive-programs | `python -m unittest discover -s tests -p "test_recursive_programs*.py" -v` | 38 | 0 | 0 | 0.015 | [log](runtime_validation/run-40714553198/op-validation-recursive-programs/unittest.txt) |

Each artifact also preserves the exact command, exit code, commit, Python version and platform. [results.json](runtime_validation/results.json) contains all 109 test identifiers and outcomes; [attempt-1.json](runtime_validation/attempt-1.json) records source fingerprints and execution provenance. Local raw-byte hashes and Git-normalized LF hashes are distinguished. The immutable tested commit supplies the exact remote files.

## Added tests

The run includes 78 existing tests and 31 new tests.

- [13 inquiry checks](../../tests/test_inquiry_op_validation.py): legal diagnostic/source episodes, cost and stopping tradeoffs, matched presentations, audit response laws, uncertain cause attribution, truthful certificates, recovery support, replay and invalid actions.
- [8 recursive-program checks](../../tests/test_recursive_programs_op_validation.py): text-session completion, stopping with residual ambiguity, query validation, deterministic replay, hidden-seed identity, inconsistent certificates despite correct answers, and rejection of observations outside the supplied affine family.
- [10 epistemic-control checks](../../tests/test_epistemic_control_op_validation.py): real game/planner interactions, depth-sensitive decisions, truthful teaching versus frozen learning, profile probing, exact planning value, truth constraints and protocol boundaries.

Independent expectations include the diagnostic two-bit outcome mapping, a one-query stop loss of 3/4 versus a two-query optimum of 3/5, audit-dependent positive-report probabilities 11/18 versus 7/18, manually specified modular-expression values, and a two-teaching planner optimum of 24/25 versus zero with only one opportunity. Agreement with independent public solvers supplements these fixtures.

## Per-idea evidence

Each row links to a new OP-labelled test. The inventory lists all applicable existing and new test identifiers, exact reproduction commands, raw logs, results, source paths and missing parts. A shared test is attributed only to the bounded behavior it exercises.

| OP | Idea | Implementation | Representative passing test | Remaining limitation |
|---|---|---|---|---|
| OP005 | Cost-dependent signal credibility | source-implemented | [`test_OP005_OP010_OP020_disclosed_audit_changes_response_law`](../../tests/test_inquiry_op_validation.py#L90) | No general signaling equilibrium or learned sender campaign is supplied. |
| OP007 | Selection policies are evidence | partial | [`test_OP007_OP023_OP075_certificate_keeps_evidence_but_changes_truth`](../../tests/test_inquiry_op_validation.py#L104) | General truthful-subset selection probabilities and unknown selection-policy inference are absent. |
| OP008 | Depth of opponent models | partial | [`test_OP008_depth_changes_defender_decision_at_fixed_truth`](../../tests/test_epistemic_control_op_validation.py#L18) | Text-session/replay integration and equal-compute capped-enumeration comparisons are absent; bounded direct game tests do not complete those experiments. |
| OP010 | Intervention changes opponent response and later evidence | source-implemented | [`test_OP005_OP010_OP020_disclosed_audit_changes_response_law`](../../tests/test_inquiry_op_validation.py#L90) | No provider experiment demonstrates an evaluated model learning an adaptive opponent. |
| OP011 | Model the opponent's model of the intervention | partial | [`test_OP011_speaker_selection_changes_interpretation_of_same_true_message`](../../tests/test_epistemic_control_op_validation.py#L29) | A paired public/private objective-disclosure experiment and text-session/replay integration are absent. |
| OP015 | Make a relevant hypothesis fail to become a question | partial | [`test_OP015_OP035_OP039_query_order_keeps_all_supplied_hypotheses`](../../tests/test_inquiry_op_validation.py#L21) | Candidate-generation suppression and evidence that a hypothesis failed to arise internally are absent. |
| OP018 | Learnable source reliability | partial | [`test_OP018_supplied_noise_changes_source_posterior`](../../tests/test_inquiry_op_validation.py#L122) | Unknown-reliability learning and matched source-identity/reliability-swap experiments are absent. |
| OP019 | Candidate generation and search allocation | partial | [`test_OP019_OP070_text_session_identifies_rules_and_scores_compositions`](../../tests/test_recursive_programs_op_validation.py#L13) | Open-ended candidate generation, discovery of an unknown grammar, and a search-allocation campaign are absent. |
| OP020 | Misclassify an adaptive opponent as stationary | partial | [`test_OP005_OP010_OP020_disclosed_audit_changes_response_law`](../../tests/test_inquiry_op_validation.py#L90) | The proposed fitted stationary-rate versus strategic-model intervention experiment is absent. |
| OP023 | Truthful subset versus falsehood versus instruction | partial | [`test_OP007_OP023_OP075_certificate_keeps_evidence_but_changes_truth`](../../tests/test_inquiry_op_validation.py#L104) | General truthful-subset selection, arbitrary framing, and a separate instruction condition are absent. |
| OP025 | Observation budget versus full transcript | source-implemented | [`test_OP025_OP045_two_observations_identify_world_and_replay`](../../tests/test_inquiry_op_validation.py#L37) | No black-box attention or candidate-generation inference follows from query choices. |
| OP028 | Add an interested participant to diagnostic environments | source-implemented | [`test_OP028_OP040_OP059_presenter_changes_first_row_cost`](../../tests/test_inquiry_op_validation.py#L66) | A learned presenter/defender campaign and unknown-opponent generalization are absent. |
| OP033 | Influencing another learner's update | partial | [`test_OP010_OP033_complete_truthful_teaching_changes_target_decision`](../../tests/test_epistemic_control_op_validation.py#L40) | Text-session/replay integration, model-aware versus stop-gradient learning experiments, and arbitrary decision-procedure modification are absent. |
| OP034 | Learning, overreaction, dogmatism, justified stability | partial | [`test_OP034_OP052_reveal_updates_quality_without_certifying_intent`](../../tests/test_inquiry_op_validation.py#L133) | A paired before/after recovery experiment with no-update and overreaction controls is absent. |
| OP035 | Same facts with different presentation | source-implemented | [`test_OP015_OP035_OP039_query_order_keeps_all_supplied_hypotheses`](../../tests/test_inquiry_op_validation.py#L21) | A randomized learned-model presentation campaign is absent. |
| OP038 | Inquiry, forecasts, outcomes and recovery differ | source-implemented | [`test_OP038_OP055_OP074_uncertain_forecast_beats_false_certainty_in_expectation`](../../tests/test_inquiry_op_validation.py#L150) | Paired recovery deltas and portfolio-level aggregation are absent. |
| OP039 | Truth and length are insufficient matching controls | source-implemented | [`test_OP015_OP035_OP039_query_order_keeps_all_supplied_hypotheses`](../../tests/test_inquiry_op_validation.py#L21) | Free-text matching or semantic equivalence verification for unrestricted messages is absent. |
| OP040 | Separate intervention construction from susceptibility | source-implemented | [`test_OP028_OP040_OP059_presenter_changes_first_row_cost`](../../tests/test_inquiry_op_validation.py#L66) | Learned construction effectiveness and population-level defender susceptibility experiments are absent. |
| OP043 | Inquiry value must include task loss and cost | source-implemented | [`test_OP043_horizon_can_reverse_stop_into_complementary_queries`](../../tests/test_inquiry_op_validation.py#L80) | No claim of scalable planning or learned inquiry ability is supported. |
| OP045 | Engine-owned truth and replayable actions | source-implemented | [`test_OP025_OP045_two_observations_identify_world_and_replay`](../../tests/test_inquiry_op_validation.py#L37) | Epistemic-control text-session/replay integration and untrusted external-process replay evidence are absent. |
| OP052 | Susceptibility, influence, and recovery are separate | partial | [`test_OP034_OP052_reveal_updates_quality_without_certifying_intent`](../../tests/test_inquiry_op_validation.py#L133) | Crossed useful-presentation/correction arms and paired initial/corrected forecasts are absent. |
| OP053 | Structured fact identity and independent seeds | source-implemented | [`test_OP053_semantic_identity_ignores_hidden_seed_and_preserves_contract`](../../tests/test_inquiry_op_validation.py#L162) | No general semantic equivalence checker for arbitrary representations is supplied. |
| OP054 | Closed action language and bounded probabilities | source-implemented | [`test_OP054_invalid_source_actions_preserve_state_and_budget`](../../tests/test_inquiry_op_validation.py#L176) | An untrusted process/container adapter and comprehensive external transport campaign are absent. |
| OP055 | Proper forecast scores | source-implemented | [`test_OP038_OP055_OP074_uncertain_forecast_beats_false_certainty_in_expectation`](../../tests/test_inquiry_op_validation.py#L150) | Empirical calibration analysis across independently sampled model episodes is absent. |
| OP059 | Agent chooses a validated presentation | partial | [`test_OP028_OP040_OP059_presenter_changes_first_row_cost`](../../tests/test_inquiry_op_validation.py#L66) | Accurate/wrong/absent profile inputs and learned profile-conditioned presentation are absent. |
| OP070 | Latent rule reconstruction rather than native representation | partial | [`test_OP019_OP070_text_session_identifies_rules_and_scores_compositions`](../../tests/test_recursive_programs_op_validation.py#L13) | General recursive rule discovery, unknown-language discovery, and cross-domain transfer beyond the supplied affine family are absent. |
| OP074 | Counterexamples against flattering capability labels | source-implemented | [`test_OP038_OP055_OP074_uncertain_forecast_beats_false_certainty_in_expectation`](../../tests/test_inquiry_op_validation.py#L150) | A comprehensive adversarial judge audit and provider-model evaluation campaign are absent. |
| OP075 | Cause identification distinct from literal truth | source-implemented | [`test_OP007_OP023_OP075_certificate_keeps_evidence_but_changes_truth`](../../tests/test_inquiry_op_validation.py#L104) | General intent detection outside the declared latent model and arbitrary natural-language communication are absent. |

## What the results establish

The three interactive environments complete tested legal episodes and reject tested invalid actions. Their scored outputs, information boundaries, seeded identities and replay behavior agree with the listed fixtures. Recursive programs identify rules within the supplied affine family and correctly evaluate tested compositions. The control core exhibits depth-dependent interpretation, information gained through probing, and specified belief updates that change later decisions. Its game and planner now have 10 executed behavioral tests in addition to the 13 existing mathematical fixtures.

The results do not establish hypothesis-generation suppression, unknown-noise learning, general truthful-subset inference, paired before/after recovery experiments, arbitrary recursive rule discovery, or arbitrary modification of a learner's decision procedure. The supplied control models do not anticipate the full teaching campaign. Its text-session and replay integrations remain absent. There are no evaluated-model capability results, broad generator sweeps, or measured campaign throughput here.

## Defects and execution issues

No test failed, and no production-code fix was required. No unresolved test exception or dependency failure occurred on the runner. Before remote execution, an Anaconda launch produced no targetable window; no local repository Python tests ran. The GitHub tree-write API returned HTTP 404 and the first SSH push connection closed; a separate-index Git snapshot and a successful retry supplied the remote branch. These were publication/infrastructure issues, not test failures.

The validation branch temporarily used the existing `recursive-gluing-eval.yml` dispatch registration with the standalone [hosted workflow](runtime_validation/hosted-workflow.yml) content. The default branch and the local sibling workflow were not changed. Snapshot commits use `[skip ci]` so publication does not initiate the general repository CI. Only the explicitly dispatched, provider-free suites above supply this evidence.

## Single highest-value remaining infrastructure gap

**A process-isolated, replayable episode runner, including the missing epistemic-control text adapter.** The control game/planner tests now pass, but that family cannot yet use the same session/replay contract as the other environments. Existing session tests use in-memory streams and trusted scripted policies. A common runner that keeps controller secrets outside the evaluated agent's process would turn these tested components into reproducible external-agent experiments. That is a concrete prerequisite to a model campaign; adding more idea families would not resolve it.
