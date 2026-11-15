# Environment audit repairs — 15 November 2026

This change implements repairs from the 11 November source audit. The audit
itself recorded no source changes. Its completion did not certify repaired
environments, and the later interactive-family test results do not validate
these older Python tasks.

## Changed evaluation contracts

- The original category starters and recurrent/ML starters lose fixed comments
  that supply the repair. Deliberately guided difficulty levels remain labeled
  assistance conditions. Complete RoPE implementations belong on the judge side.
- GNN aggregation explicitly requests the operator its judge checks. Physical
  allocation specifies clipping and proportional scaling, with capacity and
  policy checks reported separately. BatchNorm behavior no longer depends on
  touching two particular files. The monadic task permits safe literal parsing.
- Augmentation uses a specified C4 action and deterministic coverage. Tokenizer
  reconstruction has an explicit reserved-character domain. Scan chronology,
  diagonal coefficients, and the linear-attention readout are stated precisely.
- Legacy inert axis keys remain compatible with existing campaign vectors and
  are identified as controls. Parser tolerance and the hidden RoPE offset reach
  the executed checks. Schema variants no longer supply deferred constraints
  that can make the starter satisfy the target before any repair.
- All six unusual-substrate visible tests import module stems. Regex indexing
  receives one policy for direct arguments and aliases. The CSS-like task is
  explicitly a closed Boolean-selector language. Spreadsheet formulas use a
  closed grammar instead of Python evaluation. CI labels and insertion order
  no longer disclose a topological ordering. Template output is compared
  literally, including whitespace.
- Deception cases distinguish observation from mere access, accept an
  underdetermined answer when public evidence cannot identify the mechanism,
  state the audit policy, and randomize evidence order independently of the
  hidden mechanism. Signaling is labeled a policy-reading control. Explanation
  formatting is checked separately from any claim about reasoning quality.
- Trajectory solvers consistently encode payloads by integer position in the
  declaration. Format consistency compares returned states directly. Private
  cases add labels, rule orderings, and different transition graphs. Parse-only
  checks include identity, flip, and constants, so constant `same` is insufficient.

## Validation and reproducibility

The provider-free `environment-audit-validation.yml` workflow runs generation
checks, category controls, ML/recurrent controls, substrate/epistemic controls,
trajectory controls, and the existing regression suite. Generation checks
exercise every axis level in a single-axis sweep plus the combined highest
levels. They compile generated Python and smoke-import all six substrate
visible-test modules. This is not exhaustive Cartesian coverage.

Behavioral controls pair correct implementations with unchanged starters and
targeted wrong implementations. They cover the audit's value-offset soft-min,
inverse-square MoCo temperature, wrong-frequency/wrong-pairing RoPE, finite
public-corpus trajectory, numeric-order DAG, and formula-language shortcuts.
Raw outputs and generated fixtures are retained as workflow artifacts.

Agent and judge Dockerfiles use matching Torch 2.5.1 / Torchvision 0.20.1 CPU
packages. `run_eval.sh` records both built-image identities, resolved package
versions, and package-manifest hashes under `runtime_manifest/`.

All five targeted validation jobs passed at
`bfd1350b423aedd61f2c3b770c068508aa32b5df` in
[run 43688496933](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/43688496933):

| Check | Verified coverage |
|---|---|
| Generation | 270 generated variants across 37 repaired environments; Python compilation and public-boundary/import checks |
| Category | 153 baseline/reference/negative controls, zero failed expectations; 153 rendered profiles |
| ML/recurrent | 36 mathematical and halting controls, including equivalent active-row halting and wrong RoPE/MoCo constructions |
| Trajectory | 72 controls through the actual patch-validation and scoring path |
| Substrate/epistemic | 162 substrate controls, 22 additional language/shortcut probes, 240 deception cases, 24 equivalence pairs, 8 signaling cases, and 4 existing tests |

These are 423 primary behavioral controls plus the additional language and
epistemic checks. They are not model episodes. The ML probes isolate mathematics
with initialized MoCo checkpoints; they do not establish trained classifier
accuracy. Full BatchNorm/Glyph training and Docker image builds were not part
of these passing control jobs. Resolved image manifests will be produced when
the generated Docker launcher is run.

Repository-wide CI remains red. Standard CI at
[run 43688496954](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/43688496954)
has nine failing tests, all also failing in the unchanged base revision's
[run 42894396764](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/42894396764).
They concern legacy campaign plan counts, request ceilings/API configuration,
and two recursive-environment tests outside this repair set. Three base failures
were resolved: registry generation, latent metadata, and the deception privacy
assertion. No new standard-CI failure remains.

The regression job with Torch installed has one additional failure: the existing
shortcut availability test passes an incomplete fixture without a `patch` field.
Both that test and `tools/shortcut_gate.py` are byte-identical to the base Git
blobs; this path is reached when Torch is available. It is recorded separately
from the repaired judge controls, not hidden as a passing suite.

The first hosted control run, 43684121777, passed the ML, trajectory, and
substrate/epistemic suites. It exposed missing deception/signaling generation
metadata, a schema reference transaction-order error, and already-correct
tensor starters at easy/medium. The metadata and reference were repaired;
the already-correct starters are now explicit controls with no file-touch gate.
Their hard fixed-slice repair condition remains in place.

## Interpretation of historical results

Keep prior campaigns unchanged. Earlier failures under the mismatched GNN,
allocation, BatchNorm, payload, regex, or import contracts need separate
reinterpretation. Earlier passes under weak MoCo, RoPE, soft-min, trajectory,
CSS, spreadsheet, or DAG checks do not establish the strengthened property.
Cued starters and policy-reading controls must not be described as independent
discovery. New results require the repaired revision and its controls.

The Atria archives at runs 43548471464 and 43679615913 each contain 154 passing
interactive-family tests, one first-request HTTP 429 `quota_exceeded`, and no
scored model episodes. Those runs neither confirm nor refute these repairs.

No `core.py` is part of this change. The scoped recursive-family audit and the
candidate risk of scoring untrusted code in-process are not certifications of
complete oracle correctness or sandbox security.
