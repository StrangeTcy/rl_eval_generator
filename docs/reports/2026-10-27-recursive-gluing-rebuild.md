# Recursive gluing family rebuild: implementation report

Date: 2026-10-27  
Audited revision before edits: `507a62730d66a9d0b7ad8eccb62b23f72b0dd3d3`  
Execution status: source inspection and file edits only. No Python, tests,
Docker, installers, remote execution, provider calls, or model campaign were
run under the execution constraint.

## Implemented changes

### Independent expanded discovery baseline

`envs/cat_theo/recursive_gluing_discovery/files/network.py` now contains
`expanded_summaries`, which unfolds each requested type/depth into an explicit
port CSP and projects accepted root pairs with `_csp_solution`. `arm_expanded`
constructs the complete compact certificate from those projections. It no longer
calls `reference_certificate` or `compact_summaries` to manufacture the answer.

This changes the evidence available from “the compact oracle agrees with an
expanded SAT check” to “an independently constructed expanded certificate agrees
with the compact certificate” for sizes within the explicit resource limit.
It still does not make recursive discovery necessary: a sufficiently resourced
expanded solver remains a legitimate rival.

### Holonomy path dependence and scoring repair

`recursive_holonomy_gluing/files/network.py` now exposes `paths.path_a` and
`paths.path_b`, computes their ordered composites with `path_composite`, and
checks equality with `paths_agree`. The candidate certificate must include
`path_consistent`; inferred answers must include calibrated maps even when the
cycle is unsatisfiable. Affine recursive-composition instances now use distinct
ordered factors so reversing their order can change the composite.

`recursive_holonomy_gluing/files/judge.py` adds a named `path_consistency`
condition. `config.yaml` raises the PASS threshold from `0.85` to `1.0`, so a
solver cannot lose a decisive global-transport condition while passing enough
easy checks to reach PASS.

`tests/test_recursive_holonomy_gluing.py` adds a regression for the path claim
and its rejection when falsified.

This is a meaningful first repair, not a complete holonomy benchmark: the
current paths are still compact generated path lists rather than a general
multi-node transport graph, and permutation/multiplicative families need a
broader alternate-path corpus. Holonomy remains outside the readiness-gated
campaign.

### Identifiable inferred presentations

`recursive_error_correcting_codes/files/network.py` now represents calibration
as `codewords` plus `observed` presented-coordinate probes. Inferred answers
must return `perms`; the judge validates those permutations against calibration
before checking the global codeword. This replaces the former hidden
permutation that could not be recovered from the public evidence.

`recursive_coarse_graining/files/network.py` now includes an asymmetric
`probe_table` and its `observed_probe_table`. Inferred answers must return
`label_perm`, which is checked against the probe before recomputing the table
and fixed-point property.

Both environments retain direct linear algebra/table multiplication as valid
strong baselines. Recovering a presentation is now an externally checkable
subclaim, not an inferred flag hidden from the candidate.

Their tests add wrong-permutation regressions. The family study no longer pins
their representation axis to revealed; only the compiler remains pinned while
its representation contract is still being redesigned.

### Methodology updates

The existing design artifacts now distinguish:

* independent expanded solving from compact relation composition;
* mandatory holonomy global transport checks;
* identifiable calibration-based presentation recovery;
* direct algorithms that remain legitimate rivals;
* source-level implementation from executed evidence.

The all-nine source audit remains in
`docs/decisions/2026-10-26-recursive-gluing-experimental-design.md` and its
machine-readable counterpart.

## Per-environment status

| environment | current strongest evidence | remaining central weakness |
|---|---|---|
| `recursive_gluing` | explicit local/global CSP obstruction and held-out relabel/large checks | expanded CSP search solves it without latent-coordinate discovery |
| `recursive_gluing_discovery` | compact certificate versus newly independent expanded certificate | final-output judge cannot establish recursion was necessary |
| `recursive_maze_gluing` | orientation, sealing, nested route, and decoy controls | full-state BFS is a legitimate complete rival |
| `recursive_distributed_gluing` | legal interleaving replay and deadlock obstruction | scheduler-state search solves the finite task directly |
| `recursive_epistemic_gluing` | four-agent higher-order intersection and nested handwritten controls | ordinary generated cases remain shallow; enumeration is a complete rival |
| `recursive_holonomy_gluing` | mandatory path-consistency field and strict all-check scoring now implemented | needs a larger path graph, more noncommuting/alternate-path cases, and executed scorer regressions |
| `recursive_compiler_bootstrap` | finite staged encoding correctness | still not self-hosting; effective height remains capped at two |
| `recursive_error_correcting_codes` | actual calibration identifies inferred coordinate permutations | direct Gaussian elimination/brute force remains sufficient; metadata-only relabel helper remains weak |
| `recursive_coarse_graining` | asymmetric calibration identifies inferred root label permutation | direct 2×2 multiplication remains sufficient; abstraction discovery is not required |

## Checks and claims

No checks were executed after these changes. The earlier artifact
`runs/recursive_gluing_design/static_manifest_validation.json` records a prior
15/15 Node-based static validation of the earlier design state; it is not a
validation result for this rebuild and has not been overwritten.

The following remain unverified until Python 3.11+ and dependencies are
available in an explicitly separate execution environment:

* syntax/import validity of modified Python files;
* existing family test suites and the new regressions;
* equality of compact and expanded certificates across the tested vectors;
* reference/gate certification for inferred codes/coarse cases;
* holonomy path-consistency behavior across all generated families;
* judge threshold behavior in a generated environment;
* any model competence, shortcut resistance, structural inference,
  compositional generalization, or cross-domain transfer claim.

No provider campaign was authorized or launched.
