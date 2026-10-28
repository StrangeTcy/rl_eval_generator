# Existing Environment Audit

This audit is source-based. No local commands, tests, generators, or providers were run for this assignment.

## Working families and actual claims

| Registry entries | Source references | What the source supports | Adequacy |
|---|---|---|---|
| `epistemic_games` | `envs/epistemic_games/{config,files/core,files/judge}.py` | Bayesian inference over specified behavioral policies; paired observational ambiguity; structured failure modes | Good v0 for supplied evidence and posterior discipline; explicitly does not implement full recursive level-k utilities |
| `epistemic_announcements` | `envs/epistemic_announcements/files/core.py` | Exact truth classification after sequential public announcements with nested-query depth contrast | Strong finite public-announcement control; not a general theory-of-mind result |
| `epistemic_nested_knowledge` | registry and `tests/test_epistemic_nested_knowledge.py` | Nested knowledge task family | Requires mechanism and incentive controls for deception claims |
| `epistemic_fragmented_observation` | registry and `tests/test_epistemic_fragmented_observation.py` | Fragmented observation integration | Useful epistemic observation control; not strategic adaptation |
| `epistemic_silence` | registry and `tests/test_epistemic_silence.py` | Silence as an event/observation | Valuable omission precursor; archived evidence packet records it unscored, so readiness should be checked independently |
| `epistemic_type_games` | `tests/test_epistemic_type_games.py` | Pure BNE enumeration, uniqueness and partition-sensitivity certificates | Formal game baseline; does not by itself test deception attribution |
| recursive-gluing family | `envs/cat_theo/recursive_*`, `docs/decisions/2026-10-26-recursive-gluing-experimental-design.md` | Active recursive/local-to-global research track | Sibling project; preserve and reuse principles, do not duplicate implementation here |
| category/sheaf families | `envs/cat_theo/**`, Mission 01 C01–C03 | Implementation-level compositional and judge-arm stress tests | Mission 01 explicitly limits mathematical and real-agent interpretation |
| weird-machine families | `envs/weird_machine/**` | Alternate computational formalisms: regex, SQL fixed points, spreadsheets, CSS state machines, templates, CI graphs | Good representation-transfer candidates; need explicit held-out rules and anti-enumeration evidence per family |
| ML debugging | `envs/glyph`, `batchnorm_ema`, `moco`, `rope` | Interacting ML/system bugs with isolated judges and visible/hidden behavior | Strong judge infrastructure; capability interpretation remains separate from task pass rate |
| trajectory semantics | `envs/trajectory_semantics/**`, `shared/trajectory_semantics/**` | Structured trajectory parsing and solver synthesis | Valuable for externally observable intermediate artifacts; not an epistemic game |

## Registry coverage

The registry currently declares the following implementation groups; this is an audit of source presence and declared purpose, not a claim that every member is ready for a scientific campaign.

- ML/debugging: `glyph`, `batchnorm_ema`, `moco`, `rope`.
- Category/composition: `tensor_functor`, `equivariant_diagram`, `stochastic_monad`, `functorial_augmentation`, `compositional_optimizer`, `tokenizer_adjunction`, `architecture_naturality`, `transformer_ssm_lift`, `categorical_lenses`, `monadic_reward`, `semiring_unification`.
- Semiring: `ssm_parallel_scan`, `neuro_symbolic_parser`, `gnn_message_passing`.
- Sheaf/local-to-global: `sheaf_schema_sync`, `sheaf_invariant_gluing`, `sheaf_physical_constraints`.
- Recursive sibling track: `recursive_gluing`, `recursive_gluing_discovery`, `recursive_maze_gluing`, `recursive_distributed_gluing`, `recursive_epistemic_gluing`, `recursive_holonomy_gluing`, `recursive_compiler_bootstrap`, `recursive_error_correcting_codes`, `recursive_coarse_graining`.
- Epistemic: `epistemic_games`, `epistemic_announcements`, `epistemic_nested_knowledge`, `epistemic_fragmented_observation`, `epistemic_silence`, `epistemic_type_games`, plus the delivered `epistemic_deception` and `epistemic_signaling`.
- Recurrent depth: `rd_state_carry`, `rd_adaptive_halting`, `rd_gradient_credit`.
- Trajectory semantics: `ts_parse_only`, `ts_one_step`, `ts_trajectory`.
- Weird-machine: `regex_state_machine`, `sql_fixed_point`, `spreadsheet_dataflow`, `css_state_machine`, `template_interpreter`, `ci_dependency_graph`.

## Shared infrastructure already worth reusing

- Declarative `envs/registry.yaml` and difficulty matrix generation.
- Renderer hooks that bake public task and judge-only provenance.
- `shared/epistemic_semantics` for finite epistemic relations and public announcements.
- Literal answer extraction instead of executing agent answer code.
- `patch_validator`, `source_validator`, and required-file checks.
- Intervention/twin machinery, `presentation_identity.py`, `latent_spec.py`, and evaluator views.
- Campaign manifests, repeated-seed planning, oracle preflight, and failure diagnostics.

## Gaps found

1. No single existing family scores truthful accuracy, literal falsehood, omission, framing, honest error, incentive, and adaptive response as distinct fields.
2. Existing `epistemic_games` acknowledges its level-3 policy is specified behavior rather than a complete recursive utility model.
3. Archived outcomes are not sufficient evidence for capability rankings: the supplied Mercury review records 405 scored cases, 11 unscored cases, 24 endpoint-heavy environments, one seed, uneven case density, and confounded compile-only/behavioral-reference guarantees.
4. Mission 01's alternate-judge and oracle results are useful judge-audit evidence but cannot establish broad judge failure rates or mathematical sheaf claims.
5. A current explicit signaling/deception deployment slice was absent from the registry; this assignment adds it.

## Shortcut matrix

| Shortcut | Affected family | Required control |
|---|---|---|
| Always distrust conflicted role | deception | aligned/conflicted matched cases and accurate controls |
| Flag every statement as deceptive | deception | accurate and honest-error controls; separate action from mechanism |
| Memorize narrative template | epistemic games/deception | bare facts, scenario twins, held-out vocabulary and scenario |
| Enumerate supplied finite state space | epistemic/type games | held-out type partitions, payoff/topology changes, budgeted search baseline |
| Use action-only heuristic | deception | mechanism and incentive field scoring |
| Treat audit as stationary | reflexive control | disclosed/blind audit intervention and counterfactual response field |
| Exploit judge/parser | all new slices | AST literal parser, source validation, provenance rebuild, malformed answer regression |
| Infer capability from one score | entire suite | repeated seeds, mechanism-specific checks, independent reference and alternate judge |

## Prioritization rationale

The two added families are P0 because they close a uniquely important measurement gap, reuse existing judge and epistemic infrastructure, are torch-free, and support strong counterfactual controls. Reflexive control and endogenous attention follow because they require richer opponent loops. New recursive implementations are deferred to the active sibling workstream; the high-value contribution here is cross-family evidence and transfer design.
