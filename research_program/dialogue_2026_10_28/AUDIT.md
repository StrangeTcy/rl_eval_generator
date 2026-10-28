# Source audit and measurement gaps

All 50 registry entries, their configurations, and their judge files were read as source data. `environment_audit.json` records paths, hashes, declared axes, and lexically extracted check labels. Selected epistemic semantics, game generators, Arena contracts, and representative judges received direct review. A lexical check label is not a proof of its predicate, and this is not a fresh runtime audit of all 50 environments.

The audit records read-time revisions, not an atomic repository snapshot. A final fingerprint check found that the active sibling's `envs/cat_theo/recursive_compiler_bootstrap/files/judge.py` had changed since its initial audit read. Both hashes are recorded in `environment_audit.json`, `source_manifest.json`, and `static_review.json`; earlier findings remain attached to the earlier hash. The newer version received a fingerprint check only. This workstream made no changes to that file.

## Existing coverage

| Group | Source anchor | Supported object | Limitation or required next check |
|---|---|---|---|
| Supplied-policy epistemic inference | `envs/epistemic_games/files/core.py:1` | Exact Bayes over specified behavioral policies; observational ambiguity. | The module explicitly disclaims a recursively derived level-k utility model. |
| Public announcements | `envs/epistemic_announcements/files/core.py:1` | Finite S5 restriction and nested-query classification, with construction certificates. | Strong declared control against world filtering; verify the generated-case and judge pipeline in an isolated run. |
| Nested knowledge | `envs/epistemic_nested_knowledge/files/core.py:1` | Registered formula evaluation on supplied relational models and same-valuation twins. | Model checking is not discovery of hidden information structure or common knowledge. |
| Fragmented observation | `envs/epistemic_fragmented_observation/files/core.py:1` | Intersection of observation cells under exact finite semantics. | Pooling is not communication; it does not establish individual/common knowledge. |
| Silence | `envs/epistemic_silence/files/core.py:1` | Absence as an event under a specified protocol. | Reuse for omission controls; does not infer a strategic selection law. |
| Type games | `envs/epistemic_type_games/files/core.py:1` | Pure Bayesian-Nash enumeration, uniqueness, partition sensitivity. | Reuse as a game-theoretic baseline; supplied types and bounded enumeration set the claim limit. |
| T1 matched facts | `arena/matched_facts.py:1`, `:100`, `:465` | Same semantic evidence, presentation variants, terminal belief/output comparison. | Inquiry regret and recovery are explicitly not measurable without adequate interaction; `run_arm` accepts endpoint values from the answer source rather than replaying query outcomes. |
| Deception addition | `shared/deception_game.py` (`_detection_case`, `grade`) | Finite narrative label matching. | Partial visibility can remove the fact that distinguishes required answers; access opportunity is treated as knowledge; audit responses are assigned labels rather than payoff-derived actions. |
| Signaling addition | `shared/deception_game.py` (`_signal_task`, `_signal_case`) | Selecting a value from a declared table. | The public task includes the judged signal/receiver-action mapping; no numerical payoff optimization or hidden receiver inference is required. |
| ML debugging | `envs/{glyph,batchnorm_ema,moco,rope}/files/judge.py` | Training/artifact checks and domain-specific behavioral diagnostics. | Useful transfer sources for false diagnoses, but passive clues do not establish a strategic presenter or query value. |
| Category/semiring/sheaf | Registered judge paths in `environment_audit.json` | Particular identity, invariance, state isolation, or compatibility checks. | Mathematical labels do not automatically establish discovery, a universal law, or independent oracle accuracy. |
| Weird machines | `envs/weird_machine/{regex_state_machine,sql_fixed_point}/files/judge.py` and remaining registered judges | Alternative computational media; Rule 110, reachability, scheduling, and representation behavior. | Useful non-gluing transfer candidates. Fixed rules plus random inputs differ from held-out rules. |
| Recurrent depth | `envs/recurrent_depth/*/files/judge.py` | Depth/batch/gradient equivalence and halting checks. | Can distinguish implementation errors and parameter duplication; not automatically recursive-rule discovery. |
| Trajectory semantics | `envs/trajectory_semantics/*`, `arena/trajectory.py` | Relay/solver trajectory semantics and parsing. | This name does not refer to the dialogue's epistemic inquiry process. |
| Recursive-gluing sibling | `docs/decisions/2026-10-26-recursive-gluing-experimental-design.md:10` and nine registry entries | Separates behavioral competence, structural generalization, rival controls, and mechanistic evidence. | Active sibling: inspected design principles; no implementation edits or duplicate family. |

## Concrete defects in the earlier research interpretation

**Partially redacted deception cases need uncertainty.** Under partial visibility, accurate and falsehood variants can have the same positive message, access record, and redacted independent status. Merely shuffling these common evidence items cannot make the hidden fact identifiable. Nevertheless, the judge requires different mechanism labels and may require different actions. This is a source-level identifiability objection; no generated collision is claimed to have been executed.

**An answer table is not an incentive experiment.** The existing signaling task directly shows `strong/aligned -> disclose/approve`, `strong/conflicted -> frame/approve`, and corresponding weak cases. A lookup solver satisfies the grader. The new sender instead receives numerical gain, fine, private quality, and audit rate; its optimal report can reverse at the exact payoff threshold.

**Access is not knowledge, and a label is not adaptation.** The old detection generator maps all non-error cases to `knows` from a record saying the participant could inspect evidence. Its `audit_adapts` value is assigned from mechanism/incentive categories. The new source game explicitly supplies a private observation model and recomputes report probabilities under changed incentives.

**T1 is useful but incomplete for this question.** Its semantic identity and endpoint separation are sound concepts to retain. A declared diagnostic menu followed by a terminal answer does not supply engine-observed tests. The new diagnostic game adds that missing transition and computes its own regrets.

These findings do not authorize broad edits to existing cores. All changes in this delivery use new non-overlapping paths.

## Related compiler sources

The local `knowledge/README.md` and `import_manifest.json` identify the 118-node/301-edge import as provenance-preserving and externally unverified. Its original graph snapshot is retained in `related_graph.json`. Labels such as `empirically-tests` remain source annotations, not confirmations by this mission.

`research_protocol/strategy_families.yaml` supplies proposed Representation, Invariant, Asymmetry, Decomposition, Elimination, Constraint, Counterexample, Meta, Search, Game, Local-to-global, and Transformation cards. Their stated obligations inform the roadmap: preserve distinctions under representation changes, certify counterexamples, and account for search coverage. They are candidate strategies without efficacy evidence.

`mission-01/claim_set.md` records an approved **bounded** result, with failed headline thresholds and shared-oracle limitations. Its 1/12 and 4/9 bypass rates concern fixed cohorts and hand-constructed variants, not general model or judge accuracy. The 170/170 shared-dispatch agreement is not independent oracle validation. No Mission 01 result was rerun here or retroactively used as evidence for the new games.

The available local compiler checkout lacks `mission-02/`, which older target-repository notes reference. Those notes were inspected as secondary provenance; missing source snippets were not reconstructed from their descriptions. The log's purported pilot attachments and shipped `arena/epistemic.py` are not present in the primary dialogue or inspected Arena tree. Their reported numbers remain quarantined.

## Reuse and deliberate scope

The existing registry, Docker patching transport, provider adapters, and general Bayesian/S5 libraries continue serving their current tasks. The new package does not modify them. Its small exact four-state calculus serves deterministic diagnostics and stochastic strategic source reports; the separate observation-only reference uses unnormalized weights and shares neither engine nor calculus.

A future provider adapter can use existing credentials, call guards, error handling, and artifact practices after isolated readiness checks. It must transport the new public observations, not grant the agent access to controller seeds or trusted Python objects. No adapter or campaign was launched during this mission.
