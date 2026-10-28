# Recursive family: implementation and scientific readiness

Date: 2026-10-28
Status: substantial source changes; Python execution and scientific validation outstanding.

## What this pass does and does not establish

This is not a scientifically mature benchmark release. The repository now has
more explicit tasks, stronger correctness conditions, adversarial regressions,
and an executable comparison path. Those are prerequisites for interpretable
experiments, not experimental evidence that models possess the capabilities.

The workspace already contained unvalidated extensions named BootstrapMachine,
TransportGraph, KnowledgeProbe, CodePresentation, LumpingTask, and
RelationAlgebra. This pass inspected and extended them. It did not originate
every component now present. Their previous integration had missing public
specifications, outdated tests, weak negative controls, and several correctness
or reporting problems.

No Python program, pytest suite, installer, Docker job, model evaluation, or
hosted workflow was executed in this pass. Two initial read-only PowerShell
commands read the pasted mission and file inventory before its execution
restriction was known. After that, work used file reads, edits, and source-text
analysis through the file tooling. No local runtime repair was attempted.
No separately hosted Python executor was available through the enabled tools.

## Most consequential changes

### A specified minimal compiler bootstrap

Source: `envs/cat_theo/recursive_compiler_bootstrap/files/network.py`.
Protocol: the adjacent `prompt.md`.
Judge: the adjacent `judge.py`.

L1 has integer literals, one argument, sequence construction/access, arithmetic,
equality, lazy conditionals, self calls, and scoped argument binding. The VM
has flat instructions and explicit continuation frames. It has no compilation
primitive. COMPILER_SOURCE is an L1 implementation of lowering from this AST
language to that VM.

The public payload supplies the trusted executable seed but withholds compiler
source. A candidate supplies its own L1 source and all requested compiled
stages. Each stage is checked by executing the previous submitted compiler on
that source. Alternative compiler source is allowed; equality with the
repository's source is not required. Intermediate and final compilers are
tested against a separately implemented source evaluator, with lazy-branch,
binding-restoration, arithmetic, sequence, and self-call cases.

Bootstrap-chain validity and sampled semantic preservation now have separate
named judge checks. Depth d requests d+1 compilation stages and deeper
programs, for d=1..4; larger requests fail instead of silently saturating.
Candidate fuel exhaustion rejects the certificate; it does not establish a
semantic counterexample. Malformed legacy source is no longer accepted as a
counterexample, and reported source/decoded values are checked.

The legacy finite add/decoder control remains explicitly separate. The visible
decoder-only API demo has bootstrap=null; every generated grading instance
contains the full bootstrap task.

Scientific limit: this is a minimal self-hosting relationship by source-level
construction, still awaiting runtime confirmation. Finite semantic challenges
are not a compiler-correctness proof. A previously known correct L1 compiler,
or decompilation of the trusted seed, is a legitimate rival. Stages can reach a
byte-for-byte fixed implementation; performing another compilation is not
another language capability. The language and representation changes remain
small, and no model's discovery of a compiler has been measured.

### Path dependence, flatness, and sections are separate

Source: `envs/cat_theo/recursive_holonomy_gluing/files/network.py`.

Two edge-labelled loops share a base vertex. Candidates must provide full
ordered transport tables, whether the two maps agree, whether both loops are
identity, and the entire set of states fixed by both loops. A sat witness must
extend across both loops. Reordered table rows are accepted; missing states,
false flatness, malformed maps, and one-loop-only witnesses are rejected.

Depth padding now consists of nonidentity transports and a compensating
inverse composite. Affine and permutation controls have noncommuting factors.
A further case has differing nonidentity loop maps but a common section,
separating non-flatness from nonexistence of sections. An independent direct
finite-state transport route is available alongside algebraic composition.

Scientific limit: the graph is a bouquet of two loops, not a broad topology
distribution. Direct finite map composition remains sufficient. Holonomy is
still absent from `tools/recursive_references.py`'s scored gate coverage and
therefore excluded by the study profile. Strict scoring is implemented, not
yet certified by an executed generated-judge regression.

### Practical code solving and explicit ambiguity

Source: `envs/cat_theo/recursive_error_correcting_codes/files/network.py`.

CodeLinearSystem assembles local parity equations, presented-coordinate
overlaps, and the parent RHS and solves them by finite-field elimination.
The former exhaustive construction is retained as enumeration_certificate;
stacked_satisfiable remains a bounded independent search. Tests compare
these implementations on small cases and specify larger elimination cases.

Coordinate twins change matrices, permutations, calibration, and the RHS.
The identification subtask requires all admissible coordinate permutations,
a corruption syndrome, and all compatible single-coordinate corrections.
An extra probe distinguishes an otherwise ambiguous coordinate exchange.
Codeword length, integral coordinates, and field range are mandatory.
Matched parent controls differ only in their RHS.

Scientific limit: the main generated blocks are still length-two single-parity
codes; the ambiguity probe is a separate length-three single-parity task.
Such codes do not generally permit unique single-error correction. This is
not broad generalization over code families, and elimination remains a strong
complete rival.

## Status of all nine environments

| Environment | Implemented capability/control | Strong rival and remaining limitation |
|---|---|---|
| recursive_gluing | Nonfunctional monotone-relation cycles with a single closing-relation intervention; local data remain nonempty; arbitrary valid assignments accepted. | Expanded CSP/constraint propagation is sufficient. Original tree templates remain; latent coordinate discovery is not required. |
| recursive_gluing_discovery | Branching/partial relation compositions and matched closing controls. Expanded certificates are derived from unfolded CSP projections; tests inspect dependencies and compare outputs. | Direct relation iteration and expanded CSP are legitimate rivals. Expansion cap is 4; no new scaling curves were executed. Rules are supplied, so recovering an unknown grammar is not established. |
| recursive_maze_gluing | Mixed by-depth tile compositions and an orientation counterfactual. Clearing a child no longer changes the identity of an already used parent edge. | Full-state BFS is complete on bounded cases. Orientation and interfaces are explicit; latent-state discovery remains untested. |
| recursive_distributed_gluing | Seeded worker arithmetic, equivalent role/explicit-address presentations, and a matched one-versus-two lock-capacity deadlock intervention. | Scheduler-state BFS is a legitimate solver. Worker topology remains a chain and links are supplied. |
| recursive_epistemic_gluing | Four-agent modal reachability certificates, exact modal boundary perturbations, and matched nested-report cases with triple-wise compatibility but empty total intersection. Repeated formula/world evaluations are memoized. | Finite model evaluation and set intersections suffice. Product-frame nesting is factorized; arbitrary hierarchies of epistemic types and latent agent models are not covered. |
| recursive_compiler_bootstrap | Candidate-authored L1 compiler source, executable seed-to-self bootstrap, separate chain and semantic checks, actual stage/depth work, complete protocol. | Known compiler templates and seed decompilation remain alternatives. Runtime validity, broader language shifts, and universal correctness are unverified. |
| recursive_error_correcting_codes | Field elimination versus exhaustive search; transformed mathematical presentations; identifiable and ambiguous calibration; RHS interventions. | Small parity-code family and a separable ambiguity probe; no evidence for general code discovery or unique correction. |
| recursive_coarse_graining | Infer an anchored binary quotient of six- or ten-state dynamics; verify both transition commutation equations and composition predictions. One microscopic transition can destroy all admissible quotients. | Exhaustive partition enumeration remains practical. Binary anchors constrain the abstraction; the task is separable from the legacy 2x2 table calculation and does not demonstrate physical renormalization. |
| recursive_holonomy_gluing | Full transport tables, complete common-section set, noncommuting paths, and curved cases with sections; all conditions mandatory. | Small two-loop graphs and direct finite algebra. Remains excluded from scored campaigns. |

## Common experimental and reporting machinery

All nine configs now require accuracy 1.0 for PASS. Partial scores remain
available diagnostically, but a decisive global check cannot be sacrificed to
enough easy checks.

`tools/recursive_gluing_study.py` now has a StudyEvidence contract and profile
version 2. It keeps these claims distinct:

1. Competence on these generated instances.
2. Resistance to named competing algorithms under recorded resource limits.
3. Externally checked representation or invariant recovery.
4. Generalization under a declared training/evaluation composition split.
5. Cross-domain transfer under a separate source/target protocol.

Each case records paired control outcomes jointly. Missing controls remain
unobserved. The report does not infer a wrong satisfiability decision merely
from a failed combined certificate check: that failure can instead be an
invalid witness. An explicit decision diagnosis is required for that label.
No family score or automatic claim of transfer is introduced.

`tools/recursive_necessity_baselines.py --structural` extends the existing
rival runner to all nine environments and their existing grading instances.
It passes only public inputs to strategies, records source/input hashes,
solver time, certificate validity, and separate solver/oracle budget outcomes.
Strategy labels distinguish independent answer construction, shared local
semantics, references, and reference-conditioned negative controls.

The runner does not disguise reference-backed controls as independent
solvers. It also fixes the legacy scheduler sampler's conversion of resource
exhaustion into SAT: that path now fails closed. No new rival measurements
have been produced in this pass.

## Regression work written

Tests were added to all nine `tests/test_recursive_*.py` environment suites,
plus `test_recursive_apps_readiness.py` and
`test_recursive_gluing_study.py`. Their new test names start with
`test_structural_`. They include:

- matched interventions with shared local data;
- expanded-versus-compact and elimination-versus-enumeration agreement;
- false-unsat and exhausted-rival recording;
- alternate global assignments and alternate compiler source;
- JSON-round-tripped bootstrap certificates;
- corrupted, missing, and surplus compilation stages;
- semantic correctness despite incorrect bootstrap provenance;
- wrong orientation, ignored lock capacity, and premature worker execution;
- incomplete reachability, coordinate ambiguity, and malformed codewords;
- a destroyed quotient and wrong composition predictions;
- non-flat transport with a section, and a false one-loop section;
- separation of all five claims and strict PASS thresholds.

Old tests claiming a saturated compiler depth of two, or checking dependency
names in docstrings rather than executable AST references, were corrected.
Visible data examples were updated where their calibration/transport schemas
had become stale.

These are written regressions, not passing regressions.

The final source review also corrected contradictory identity defaults in the
codes and coarse-graining prompts: missing permutations in inferred mode must
be recovered from calibration. It extended transport-table rejection to
malformed or excessively long sequences and added a regression. Legacy tests
were adapted where the new mandatory certificates invalidate an old stub or
return a zero-valued rejection indicator.

Four older held-out tests wrote a fixed `reference_acc: 1.0` without verifying
reference certificates. Those report writes were removed and replaced by
explicit positive/negative certificate assertions. The epistemic metric test
also no longer overwrites a historically dated report. Future measured rival
artifacts come from the runner, with source/input hashes and observed outcomes.
Historical audit artifacts are not evidence for this revision.

## Checks executed and reproduction

The machine-readable source review is
`docs/reports/2026-10-28-structural-source-review.json`. It records the exact
file-text checks performed and current digests. Delimiter scans and field-name
checks do not establish Python syntax, importability, runtime behavior, or
mathematical correctness.

The final file-text checks found no unmatched delimiters or strings in the
reviewed Python sources, no missing network symbols imported by the nine
judges, and no declared check missing from the builders or judge assignments.
The JSON design manifest parsed, and its counts agree with the current source:
18 diagnostic episodes / 196 checks, 24 screen episodes / 234 checks, and
38 unique combined episodes / 386 checks. These are static accounting results.

The manual workflow
`.github/workflows/recursive-structural-validation.yml` targets a hosted
Ubuntu/Python 3.11 runner and has no provider credentials or campaign step.
It has not been dispatched. It installs only the declared test dependencies,
runs the nine environment suites plus readiness, study, and reference-gate
tests, then records algorithm rivals. Its exact commands are in the workflow.
Source inspection found PyYAML and pytest on the selected host-test paths.
The shared runtime judge imports PyTorch; full generated-judge execution uses
the separate container gate and is not certified by this host-test workflow.

The isolated runner must execute, at minimum:

```text
python -m pip install -r requirements.txt
python -m pytest tests/test_recursive_gluing.py tests/test_recursive_gluing_discovery.py tests/test_recursive_maze_gluing.py tests/test_recursive_distributed_gluing.py tests/test_recursive_epistemic_gluing.py tests/test_recursive_compiler_bootstrap.py tests/test_recursive_error_correcting_codes.py tests/test_recursive_coarse_graining.py tests/test_recursive_holonomy_gluing.py tests/test_recursive_apps_readiness.py tests/test_recursive_gluing_study.py tests/test_instance_oracle_reference.py --junitxml=structural-validation.xml
python tools/recursive_necessity_baselines.py --structural --depth 2 --seed 41 --json structural-rivals.json
```

Do not interpret those commands as having run. Any failing regression,
including an inherited test made stale by a new contract, remains work to
resolve in the isolated environment. Full exact-instance container-gate
certification is separate from these Python tests and is also outstanding.

## What scientific maturity still requires

First establish that the implementation executes correctly: import/syntax
checks, the complete regression suites, generated judge behavior, alternative
certificate acceptance, and exact-instance positive/negative gates.

Then measure the competitors on matched public inputs, multiple sizes and
seeds, both polarities, and explicit time/memory/node budgets. Code currently
implements many direct rivals; success by those rivals should narrow the
claim rather than be suppressed.

Preregister training/evaluation splits with disjoint compositions and
presentations. A within-episode hidden check is not a training-to-test transfer
experiment. Separate invariant recovery from arbitrary coordinate naming,
and analyze underdetermined calibrations as equivalence classes.

The compiler needs additional independently authored wrong compilers,
construct combinations, trust-chain tests, and larger representation shifts.
The maze and distributed tasks need genuinely inferred interfaces/topologies.
The code and quotient tasks need broader families, and holonomy needs more
graph topologies. Some newly required structural certificates are separable
from the legacy tasks; passing both does not show one common learned
representation.

Only after that should authorized model experiments test competence,
shortcut resistance, structural inference, generalization, or cross-domain
transfer. None of those model-level claims is established here.
