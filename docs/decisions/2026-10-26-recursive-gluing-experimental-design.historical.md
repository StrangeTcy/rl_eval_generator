# Recursive gluing experimental design and run manifest

Date: 2026-10-26  
Source revision audited: `507a627`  
Status: design and provider-free validation only; no external model calls have
been made for this manifest.

## Decision summary

This design separates four claims:

1. **Behavioral competence:** a submitted solver earns a perfect score on the
   judge's hidden checks for the generated episode.
2. **Held-out structural generalization:** the solver also succeeds on the
   judge's named decoy, relabelled, twisted, large, nested, or negative checks,
   and on a different generation seed where specified.
3. **Evidence consistent with rule reconstruction:** success survives the
   explicit local-only/copy-upward rival controls and the cases designed to
   make those rivals fail.
4. **Mechanistic evidence:** an independently recorded trace or intervention
   demonstrates the claimed composition rule. The current scored episode does
   not provide this by itself.

A passing solver is evidence for level 1. The hidden-check breakdown can support
level 2 and, with the rival controls, level 3 as a behavioural claim. None of
these is proof of the model's internal reasoning mechanism.

The machine-readable manifest is
[`2026-10-26-recursive-gluing-experimental-design.json`](2026-10-26-recursive-gluing-experimental-design.json).

## Scope and status labels

| scope | cases | seeds | status | purpose |
|---|---:|---|---|---|
| primary diagnostic | 18 | the curated `0` cells plus two fixed `1` stability cells | diagnostic; not confirmatory | distinguish the principal expanded-control and compact-grammar rivals |
| family screen | 24 | `0` | exploratory | one common, readable screen for the eight gateable family members |
| confirmatory model campaign | 0 launched | not applicable | planned only | requires replication and the additional necessity test below |

The family screen is the existing `scope=family, matrix=diagnostic` design:
three exact vectors per eligible environment. Four family rows are byte-for-byte
case-identity duplicates of primary diagnostic rows, so a combined campaign can
reuse their results rather than paying for duplicate episodes. The union is 38
unique episodes for one model/provider.

## Controls and evidence contract

Every generated episode needs these controls before a model result is used:

* **Positive control:** the environment oracle embedded by
  `tools/recursive_references.py` passes the real judge at score `1.0`.
* **Negative control:** the named plausible shortcut fails its designated hidden
  decision check. An empty/no-op submission must also score `0`.
* **Exact-instance gate:** the controls are run on the exact generated instance,
  not on a nearby example. A failed gate is an oracle/readiness failure, not a
  model failure.

The strict result criterion for a model episode is `validated_success`: a
scored `PASS` with score `1.0`, with all observed hidden checks true and no
provider, timeout, infrastructure, or missing-result outcome. The environment's
published `0.85` pass threshold remains visible, but a threshold pass is not
enough for the stronger claims in this document.

The hidden-check counts below are counts of named judge check instances exercised
by one episode. They are not claims that those checks are independent identically
distributed statistical samples; the report must retain their names and
semantics.

The evidence bundle for every episode is: frozen manifest and config hashes,
generation/provenance record, prompt and visible tests, agent action/tool log,
`model_responses.jsonl`, final submission, judge `final.json`, hidden-check
breakdown, usage/latency, controller checkpoint, and the positive/negative gate
report. The manifest, plan, gate report, checkpoint, JSON/CSV/Markdown report,
and commit SHA are the reproducibility artifacts for a dispatch.

## Primary 18-case diagnostic manifest

The configuration is the exact ordered difficulty vector accepted by the current
config. The seed is not replaced or remapped. `Δ` lists what changes from the
matched comparison; it explicitly records confounding where a diagnostic cell
does not isolate one axis.

### `recursive_gluing` — expanded control, 8 episodes

| case | exact configuration | seed | Δ from matched comparison | claim / strongest rival |
|---|---|---:|---|---|
| `baseline_tree_sat` | `recursive_depth=easy,state_space=easy,gluing_regime=easy,label_opacity=easy` | 0 | anchor | competence on a transparent tree; rival: hard-coded visible examples |
| `cyclic_sat` | `medium,medium,medium,easy` | 0 | depth, state space, and regime move from baseline | can solve a cyclic satisfiable network; rival: tree-only propagation or answer-class prior |
| `cyclic_unsat_locally_nonempty` | `medium,medium,hard,easy` | 0 | regime only, `cyclic_sat → cyclic_unsat` | can detect a global obstruction despite nonempty local tables; rival: local nonemptiness or SAT prior |
| `opaque_labels` | `medium,medium,medium,hard` | 0 | opacity only, from cyclic SAT | answer invariant under relabelling; rival: label/name heuristic |
| `opacity_x_unsat` | `medium,medium,hard,hard` | 0 | opacity only, from cyclic UNSAT | compose constraints under opacity and obstruction; rival: copy local table upward |
| `nested_tree_opaque` | `medium,medium,easy,hard` | 0 | regime and opacity relative to cyclic SAT | depth without a cycle; rival: cycle-specific heuristic or readable names |
| `max_depth_unsat` | `hard,hard,hard,hard` | 0 | depth and state space move from the interaction cell | stress competence; rival: memorised medium-size pattern |
| `max_depth_unsat_stability_seed` | `hard,hard,hard,hard` | 1 | seed only from the preceding case | seed stability; rival: generator-specific luck |

For this environment, the positive control is `reference_solve`; the negative
control is the explicit greedy cross-depth shortcut in
`recursive_references.py`. The gate's named negative check is
`obstructed_cycle` (and the generated-cycle check is `cyclic_unsat_generated`).
There are 10 judge check instances per model episode:
`local_path_sat`, `configured`, `solvable_cycle`, `obstructed_cycle`,
`nested_recursive`, `cyclic_sat_generated`, `cyclic_unsat_generated`,
`relabel_twin`, `heldout_large`, and `deterministic`.

### `recursive_gluing_discovery` — compact grammar, 10 episodes

Axis order is `recursive_depth,state_space,gluing_regime,label_opacity,structural_ambiguity`.

| case | exact configuration | seed | Δ from matched comparison | claim / strongest rival |
|---|---|---:|---|---|
| `baseline_tree_sat` | `easy,easy,easy,easy,easy` | 0 | anchor | compact-summary competence; rival: visible-example memorisation |
| `cyclic_sat` | `medium,medium,medium,easy,easy` | 0 | depth, interface size, and regime move from baseline | composition on a closing relation; rival: direct expansion or SAT prior |
| `cyclic_unsat_locally_nonempty` | `medium,medium,hard,easy,easy` | 0 | regime only from cyclic SAT | reject a globally impossible closing; rival: local-table nonemptiness |
| `opaque_labels` | `medium,medium,medium,hard,easy` | 0 | opacity only from cyclic SAT | transport through tables rather than names; rival: port-name heuristic |
| `decoy_leaf` | `medium,medium,medium,easy,hard` | 0 | structural ambiguity only from cyclic SAT | select the correct production; rival: copy the first/leaf table |
| `copy_upward_foil` | `medium,medium,hard,easy,hard` | 0 | regime only from the decoy cell | decoy plus obstruction defeats copy-upward; rival: the shipped `arm_copy_leaf_upward` |
| `opacity_x_unsat` | `medium,medium,hard,hard,easy` | 0 | opacity only from cyclic UNSAT | compose an opaque obstruction; rival: local propagation plus answer prior |
| `max_depth_unsat` | `hard,hard,hard,hard,hard` | 0 | depth, interface size, opacity, and ambiguity move from the foil | depth-indexed rule reconstruction behaviour; rival: expanded materialisation |
| `max_depth_sat` | `hard,medium,medium,hard,easy` | 0 | depth held hard while state/regime/ambiguity move toward SAT | separates depth from answer polarity; rival: answer-class heuristic |
| `max_depth_unsat_stability_seed` | `hard,hard,hard,hard,hard` | 1 | seed only from the maximum UNSAT case | seed stability; rival: generator-specific luck |

The positive control is `reference_certificate`; the negative control is
`arm_copy_leaf_upward`. The gate's named negative check is `assembled_unsat`.
There are 8 judge check instances per model episode:
`local_visible`, `configured`, `assembled_sat`, `assembled_unsat`,
`opaque_twin`, `decoy_heldout`, `heldout_twist`, and `deterministic`.

### What this diagnostic can and cannot establish

It can diagnose competence, expose the local/copy-upward rival, and test several
held-out structural variants. It cannot establish that recursive discovery was
necessary: the expanded CSP baseline is a real rival and currently solves the
recorded hard compact instance at depth 12 in about one second on the scaling
machine. Correctness on the compact representation therefore remains
behavioural evidence, not proof of a discovered or necessary algorithm.

The necessity claim is **blocked** until the benchmark supplies a matched
expanded-materialisation twin for the same compact grammar, depth, seed and
budget, plus a pre-registered resource/correctness comparison at depths where
the expanded rival fails or exceeds the same resource limit. A model judge that
only scores the final certificate cannot observe algorithmic necessity.

## Eight-environment exploratory family screen

All rows below use seed `0`. Within each environment:

* `family_baseline` is the first level of every axis.
* `family_obstruction` changes only the regime/family axis to its hardest level.
  This is the matched obstruction comparison.
* `family_maximum` changes every axis to its hardest level, then applies the
  remaining `representation=revealed` pin for compiler. Codes and
  coarse-graining now expose identifiable calibration evidence for inferred
  presentations. It is a stress/generalization cell, not a clean main effect.

| environment | baseline | obstruction | maximum | hidden checks / negative control |
|---|---|---|---|---|
| `recursive_gluing` | `easy,easy,easy,easy` | `easy,easy,hard,easy` | `hard,hard,hard,hard` | 10 / greedy cross-depth propagation |
| `recursive_gluing_discovery` | `easy,easy,easy,easy,easy` | `easy,easy,hard,easy,easy` | `hard,hard,hard,hard,hard` | 8 / `arm_copy_leaf_upward` |
| `recursive_maze_gluing` | `easy,easy,easy,easy` | `easy,hard,easy,easy` | `hard,hard,hard,hard` | 7 / explicit flat-root search |
| `recursive_distributed_gluing` | `easy,easy,easy` | `easy,hard,easy` | `hard,hard,hard` | 6 / `arm_numbers_only` |
| `recursive_epistemic_gluing` | `easy,easy,easy,easy` | `easy,hard,easy,easy` | `hard,hard,hard,hard` | 9 / `arm_actual_facts` |
| `recursive_compiler_bootstrap` | `easy,easy,easy` | `easy,hard,easy` | `hard,hard,easy` | 7 / `arm_local_only` |
| `recursive_error_correcting_codes` | `easy,easy,easy` | `easy,hard,easy` | `hard,hard,easy` | 7 / `arm_local_only` |
| `recursive_coarse_graining` | `easy,easy,easy` | `easy,hard,easy` | `hard,hard,easy` | 7 / `arm_local_only` |

Axis order follows each environment's `config.yaml`; the values above are
level names, not an assumed ordinal difficulty score. The family screen can
compare concrete global-correctness competence across domains, but it does not
identify cross-domain transfer of one structural algorithm: the tasks expose
different state spaces, answer objects, and rival algorithms. It is exploratory
because the tasks, answer classes, topologies, and latent factors differ, and
the configs currently mark their causal-factor declarations as
`scaffold_unreviewed`.

`recursive_holonomy_gluing` is intentionally absent from the readiness-gated
screen. Its scorer now requires all checks and its path-consistency condition,
but it remains outside scientific evaluation until the expanded path/topology
regression matrix is executed.

`recursive_compiler_bootstrap` is included only as an exploratory composition
task. Its configured hard depth is `3`, but the generator caps program height
at `2`; it must not be used for a depth-scaling claim until that saturation is
removed or the manipulation is redesigned.

## Model-run accounting

The numbers below are planning ceilings for the current controller, not observed
usage. With `max_steps=24`, `max_tokens=4096`, and `invalid_retries=2`, one case
has at most `24 × (1 + 2) = 72` logical API calls and `294,912` output tokens.

| dispatch | model episodes | judge check instances | expected logical calls | output-token ceiling | recommended wall ceiling |
|---|---:|---:|---:|---:|---:|
| diagnostic, one provider/model | 18 | 160 | 1,296 | 5,308,416 | 14,400 s |
| family screen, one provider/model | 24 | 183 | 1,728 | 7,077,888 | 18,000 s |
| unique union with duplicate case ids reused | 38 | 307 | 2,736 | 11,206,656 | split into dispatches |

The family dispatch should use `max_api_calls=2000`,
`max_tokens_total=8000000`, `max_wall_seconds=18000`, and the controller's
derived physical-attempt budget. The diagnostic defaults in the current
workflow cover its arithmetic. These are not dollar estimates and do not
include GitHub queue time.

Each row is one model episode per provider/model. To support a confirmatory
claim, repeat the pre-registered primary contrasts on at least three additional
independent seeds or model episodes, retain the exact same controls, and report
per-seed outcomes rather than pooling failures with infrastructure pauses. The
current 18-case matrix has only two seed-1 stability rows and is therefore a
diagnostic design, not a confirmatory sample.

## Reproducibility and analysis rules

Report per case, environment, factor, seed, and hidden check. Do not report one
pooled pass rate across the expanded control, compact discovery, or the family
members. Treat provider failure, timeout, missing result, infrastructure failure,
oracle failure, and gate failure as non-scores. Keep the following levels in
separate report sections:

* **competence:** exact-instance gate passed and model scored `validated_success`;
* **held-out generalization:** named hidden checks and seed replication;
* **rule reconstruction evidence:** rival shortcut failures plus success on
  decoy/opaque/twist/negative variants;
* **mechanism:** only independently captured traces/interventions that expose
  the composition process.

No model-run result is present in this repository state. The provider-free checks
and their exact availability are recorded in the companion validation report.

## Source audit against all nine family members

This section is a source-based audit of revision `507a627`. It was performed by
inspection only; no Python, tests, Docker, provider, or model execution was used.
The terms below describe what the implementation actually exposes, not what a
successful score would prove.

Across the family, the model-facing action is program synthesis: it edits
`solver.py` and returns a certificate through `solve`. The harness records the
agent/tool transcript, but the judges score only the returned certificate or
trace. No current judge requires an inspectable intermediate coordinate system,
summary table, search trace, or invariant discovery log. Consequently all
mechanistic conclusions below are underidentified by the present action
interface; hidden checks can rule out specific rivals behaviorally but cannot
observe which algorithm produced the answer.

| environment | observable local data and global candidate | property actually tested | strongest passing shortcut | source-based assessment |
|---|---|---|---|---|
| `recursive_gluing` | `network.py:generate_instance` exposes domains and explicit overlap pair relations; a global section is an assignment accepted by every overlap. Hidden `frames` and carrier values generate the relations but are not observed. | Finite binary CSP gluing: locally nonempty domains/overlaps can have no global assignment. Cycles and skip-level overlaps are explicit. | AC-3/MRV/backtracking or full Cartesian search over the expanded graph; no carrier-coordinate discovery is needed because every correspondence is listed in `overlaps`. | The 8 cases are valid local-global competence diagnostics. They are not evidence that a model inferred a hidden coordinate system. `heldout_large` is fixed at depth 3/domain 7 in `build_grade_instances`, so the configured depth/domain axes do not control the largest hidden check. |
| `recursive_gluing_discovery` | `prompt.md` exposes module types, leaf pair tables, production choices, and all enter/mid/leave wiring. A global candidate is the complete type/depth summary plus a root pair accepted by `closing`. | Recursive relation composition: `compose_branch` transports compatible child interface pairs; `compact_summaries` computes the inductive global section. | Expanded CSP search via `expand_grammar`/`_csp_solution`, or a direct finite-state table algorithm. `arm_expanded` now constructs the required certificate from independent expanded CSP projections rather than delegating to the compact oracle. | This is a compact-certificate task, not a proof of recursive discovery. `MAX_EXPAND_DEPTH=4` still limits the shipped cross-check at hard depth 12, while a separately resourced larger expansion remains the substantive rival. Necessity remains unestablished by final-answer scoring. |
| `recursive_maze_gluing` | Tiles expose rooms, directed edges with XOR `flip`, shafts, nesting, start/goal orientation, and sealing. A global section is a legal stack-aware route whose boundary room/orientation states match on descent/return. | Nested route composition with a \(\mathbb Z/2\mathbb Z\) transport invariant; the obstruction is a nonzero accumulated flip or an uncompleted sealed child. | BFS over `(stack, room, orientation, cleared, used edges)` exactly as `shortest_route`, without deriving a reusable tile summary. | The orientation foil and decoy/held-out maze checks are meaningful controls against ignoring flips or child type. They do not isolate recursive reasoning from explicit state-space search. Depth changes the search state, but the family screen's obstruction cell is depth 1 and its maximum cell is a confounded all-hard stress case. |
| `recursive_distributed_gluing` | Worker programs, parent/child links, mailbox operations, mutex count, and input are public. A global section is a complete interleaving accepted by `replay_trace`, with all programs finished and no lock held. | Concurrent global compatibility: local program legality does not imply a schedulable interleaving; the obstruction is a wait-for cycle while locks are held. | BFS over program counters, inboxes, mailboxes, lock state, and values, exactly the strategy in `shortest_trace`; worker renaming is only a presentation twin because links remain explicit. | The negative schedule and trace replay distinguish “return a number” from a legal schedule. They do not test latent interface discovery or recursive composition beyond a linear worker chain. Retain as exploratory scheduling competence only. |
| `recursive_epistemic_gluing` | Frames expose worlds, atoms, and each agent's indistinguishability partition; `bundle` and `nested_bundle` name local views. A global section is a world in every selected cell, or a chain satisfying the modal query. | Intersection of local information cells, modal truth over the product of frame chains, and nested truncation effects. `bundle_possible` checks outer and inner intersections independently. | Direct enumeration of all chains in `all_chains` and modal evaluation in `eval_formula`; for bundles, direct set intersection. | `NEG_DEEP` (four agents, all 3-wise intersections nonempty but total intersection empty) and `NEG_RECURSIVE` are real counterexamples to local/pairwise and truncation shortcuts. They support global-intersection and nesting claims, not hidden-coordinate discovery or recursive composition. Generated ordinary cases have two agents and no `nested_bundle`; the stronger controls come from handwritten grade cases. |
| `recursive_holonomy_gluing` | Maps are either revealed directly or recoverable from calibration; the cycle list and order are public. A global candidate is a state fixed by the composite transport, plus maps when representation is inferred. | Fixed-point compatibility of a finite composite map. Local maps are transports; a global section is a returning state; no fixed state is the obstruction. | Compose the named maps directly and enumerate fixed states. In inferred mode, `calibrate` gives enough points to reconstruct every map family exactly. | The current implementation does **not** expose genuine path dependence: generated cycles contain identities plus at most one extra factor (`generate_instance`, lines 194–209), so there are no alternate paths or competing noncommuting transports. It tests fixed points, not holonomy in the strong path-dependent sense. |
| `recursive_compiler_bootstrap` | Source programs, stages, claimed decoder, calibration, and (when revealed) encodings are public. A global candidate is observational equivalence on the listed finite program set. | Composition of compiler/encoding stages; local stage correctness can coexist with a wrong decoder for the composed path. | Execute every listed source program through compile → encode → claimed decode, or return a counterexample. No recursive compiler self-application is implemented. | `MAX_PROGRAM_HEIGHT=2` caps the effective depth; requested hard depth 3 equals height 2. The finite listed program set and visible `claimed_decoder` make direct testing sufficient. Retain only as exploratory encoding-composition competence, never as depth scaling or self-compilation evidence. |
| `recursive_error_correcting_codes` | Length-2 parity blocks, coordinate permutations, glues, and a parent linear equation are public in revealed mode; a global section is a block assignment satisfying all local kernels, glues, and the parent check. In inferred mode, codeword/observed calibration pairs expose the presentation permutation without revealing it directly. | Linear local-to-global consistency over \(\mathbb F_5\); nonempty local kernels can have an empty stacked solution set. | Gaussian elimination or brute force over at most six coordinates (`stacked_satisfiable`); no recursive algorithm is required. | The obstruction cell distinguishes local-only from global solving. The inferred representation now has an externally checkable identifiability condition, but direct linear solving remains the strongest rival. `relabel_instance` is still metadata-only and should not be used as the presentation-twin claim. |
| `recursive_coarse_graining` | Local nonnegative three-index weights, a series tree, and an asymmetric calibration probe with its presented version. A global candidate is the exact effective transfer table and whether it is idempotent under table composition. | Sum-product transfer-matrix composition and a fixed-point test, not a CSP or sheaf of compatible local sections. | Multiply 2×2 transfer tables directly; depth 1 is always one region for `direct`/`flat`, and fixed/nonfixed is determined by the generated weight family. | The obstruction cell can reject a first-region-only shortcut. Inferred mode now requires recovering the root label permutation from asymmetric calibration, but direct table multiplication remains a valid rival and the task still does not require latent recursive discovery. |

### Operational sheaf reading, with limits

The sheaf-like language is operational only for the first five rows, and even
there it has different concrete meanings:

* In `recursive_gluing`, local sections are domain values and restrictions are
  overlap relations. A global section is a total assignment. `semantic_issues`,
  `validate_assignment`, and `oracle_solution` make compatibility explicit.
* In discovery, local sections are `(enter, leave)` relations for a type at a
  remaining depth. Wiring tables are restriction/transport maps; `compose_branch`
  is their relational composition; `closing` is the final compatibility
  restriction.
* In the maze, local sections are entrance-to-exit walks with an orientation
  state. Shafts are boundary restrictions and a global route is a stack-compatible
  witness. The accumulated XOR flip is the concrete transport invariant.
* In distributed scheduling, local sections are program prefixes with local
  mailbox/lock state. Send/receive and mutex occupancy are boundary compatibility;
  a global section is an interleaving accepted by `replay_trace`.
* In epistemic models, local sections are indistinguishability cells. The
  compatibility condition is literal set intersection, and the global section is
  a world/chain in all selected cells. The implementation deliberately tests
  failure of pairwise or truncated compatibility.

Holonomy is only partially represented: `compose_specs` supplies ordered
transport and `fixed_states` tests return to the starting point, but the generator
does not provide two paths with the same endpoints whose transports differ. A
real holonomy control requires at least two non-identity, noncommuting factors or
two explicitly comparable paths and a held-out path-order reversal.

The compiler, code, and coarse-graining tasks are mathematically meaningful but
should not be forced into a sheaf interpretation. Their global objects are an
observationally equivalent decoder, a stacked linear codeword, and a composed
transfer table respectively.

## Matrix review and disposition

The existing matrix remains useful only with narrower labels:

* **Retain as diagnostic:** all 18 primary cases, but interpret them as CSP and
  compact-certificate diagnostics. They can rule out the named local/copy-upward
  baselines when the exact hidden checks fail those baselines. They cannot show
  latent-coordinate discovery or make recursive discovery necessary.
* **Retain as exploratory competence:** the 24 eligible-family rows for maze,
  distributed, epistemic, compiler, codes, and coarse-graining. Their controls
  distinguish concrete global correctness failures, but explicit BFS, algebra,
  enumeration, or matrix multiplication remain valid rival algorithms.
* **Do not retain for a structural-reasoning claim:** any pooled family result,
  compiler depth comparison, inferred-representation result for codes/coarse,
  or discovery result described as evidence that expansion was impossible.
* **Holonomy research lane:** do not launch the current scored holonomy arm. It
  needs a scorer repair and a generator repair for path dependence first. It
  should nevertheless remain in the audit and in a future static/reference
  validation lane.

### Holonomy scoring defect and required repair

Before this repair, `files/judge.py` computed accuracy as
`passed / len(CHECK_NAMES)` and the config threshold was `0.85`. There were
seven checks, so six passes (`6/7 = 0.857`) were enough for PASS. A wrong solver
could therefore fail one decisive global transport check while passing the
visible case, SAT controls, relabel twin, and other checks. The repository's
recorded audit
`docs/audits/2026-10-16-holonomy-baselines.json` covers 12 known UNSAT cases for
the local-only baseline, but it does not certify a per-check adversarial matrix or
the current judge's seven-check aggregate.

The implementation now sets `pass_threshold=1.0`, adds a named mandatory
`path_consistency` check, and requires the certificate to report the comparison
of two generated transport paths. A discriminating holonomy evaluation still
requires named cases for:

1. the same local maps with a globally fixed and globally non-fixed composite;
2. an order reversal or alternate path whose composite differs;
3. revealed and calibration-only map recovery;
4. a coordinate-conjugate twin preserving fixed-point truth; and
5. a known-wrong local-consistency solver that is required to fail every global
   obstruction cell.

Until those checks exist and are executed, holonomy has a source-level design
finding, not a model result.

## Claims that remain unverified

This audit establishes the mechanics by source inspection. It does not establish
that the reference controls pass after generation, that any wrong arm fails on
every proposed vector, that the current gates certify all family rows, or that a
model uses any particular algorithm. Those claims require the repository's
Python tests/reference gates and, for competence, model episodes. None was run
under the present execution constraint.
