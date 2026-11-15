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

Validation status: awaiting the hosted checks for this revision. The report
will be updated with their result before this repair work is declared complete.

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
