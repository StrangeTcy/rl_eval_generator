# Recursive production gate continuation

Date: 2026-11-09

The subsequent hosted run passed all 72 controls. See the
[completed two-track report](2026-11-09-two-track-continuation.md) for the
tested revision, run links, independent artifact audit, and remaining limits.
The preparation record below is retained for provenance.

The hosted workflow now executes the JavaScript evidence harness already
present in the working tree. The previous workflow still selected the older
Python harness, so the preserved frozen-instance checks and eight-variant
matrix were not connected to its launch path.

The workflow uses Node.js 22, Python 3.11, CPU PyTorch 2.5.1, and torchvision
0.20.1. It accepts an explicit revision through manual dispatch and runs on
pushes to `codex/recursive-production-20261109`. It uses no model-provider
credentials. The historical Python harness remains available as prior evidence.

## Additional certificate control

Each of the eight scored environments now receives nine submissions:
valid, valid repeat, unchanged baseline, incomplete certificate, malformed
source, malformed certificate, corrupted certificate, the same corrupted
certificate with `reference_acc=1.0`, and metadata alone.

The new corruption pair must produce identical named checks, raw accuracy,
and final score. Both submissions must fail the production judge. This checks
whether a declared reference accuracy can rescue a structurally invalid
certificate. The existing metadata-only control still requires zero accepted
hidden checks and zero score.

Evidence acceptance additionally requires the recorded hidden-check count and
raw accuracy to agree with the named checks. Retained outputs must contain
every payload name and both solver outputs; two missing output fields cannot
be accepted as deterministic repetition. Unknown control names fail closed.
Infrastructure errors remain separate from expected certificate rejection.

The expected matrix is 72 submissions: eight environments times nine variants.
`recursive_holonomy_gluing` remains outside the scored gate. The generated
judge, environment algorithms, scoring thresholds, and `core.py` are unchanged
by this continuation.

## Local checks

Commands executed successfully:

```text
node --test tests/test_recursive_structural_production_gate.mjs
node tools/recursive_structural_production_gate.mjs --self-test
node --check tools/recursive_structural_production_gate.mjs
node --check tests/test_recursive_structural_production_gate.mjs
```

Results: 16 JavaScript regression tests passed, and the original eight
evidence-classification/source-preservation assertions passed. A separate
digest comparison found no changed reviewed recursive environment source
against `docs/artifacts/recursive-structural-validation-2026-11-02/validation-record.json`,
allowing the same line-ending normalization as the hosted harness.

Launch preflight now reads all 58 required source files and verifies all eight
frozen ZIP archives without executing Python. It checks each recorded file
hash, the complete tree and judge hashes, the historical generation/pair IDs,
and the reconstructed generation ID. Regression cases remove the reset log
or alter its recorded identity in a temporary copy; both prevent launch.

The historical reset log was absent from the working tree. Its exact 19,805
bytes were recovered from the parent Git revision into
`tools/fixtures/recursive-structural-production/historical-production-reset.log`.
The launch depends on that retained fixture and does not require restoring the
absent historical path in the working tree. The preflight result is retained
as `launch-preflight.json` during hosted production execution.

These checks validate evidence handling and candidate construction. They do
not execute the Python judges or establish environment production validity.
The hosted run must provide `production-judge-results.json`, per-case raw judge
JSON and exits, preserved PyTorch outputs, source hashes, and the final report.
Successful production execution would remain evidence for these frozen inputs,
not evidence of model recursive reasoning, generalization, or transfer.
