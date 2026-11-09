# Recursive production validation and truthful evidence selection

Both targeted hosted workflows passed at revision
`a7979ef6ce58f9993ccaaa569ddd7d3f12783310` on 9 November 2026.

## Recursive environment family

[Production run 42647776111](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/42647776111)
executed all 72 submissions across the eight scored recursive environments.
Each environment passed all nine controls: valid, valid repeat, unchanged
baseline, incomplete certificate, malformed source, malformed certificate,
corrupted certificate, the same corruption with `reference_acc=1.0`, and
metadata alone. The 16 valid submissions passed their production judges and
the 56 negative submissions were rejected as expected. All eight fresh-repeat
comparisons and all eight metadata-noninterference comparisons passed.

The gate uses the production `env_runner` and judges with Python 3.11.18,
CPU PyTorch 2.5.1 and torchvision 0.20.1 on hosted Ubuntu 22.04. It retains
raw judge JSON, process exits, submitted sources, frozen identity verification,
and serialized evaluation output. Sixteen Node regressions and launch checks
for 58 source files and eight archives also passed. Holonomy remains excluded.

The first hosted attempt, run 42633588476, stopped before production execution:
Git normalized mixed line endings in seven reviewed prompts. Targeted
`.gitattributes` entries now preserve those exact bytes. The strict historical
hash checks remain intact. A separate check rebuilt all required inputs from
the committed Git blobs and passed before the successful push.

This closes the prior missing-production-execution gap for these frozen cases.
It provides no evidence that recursion is necessary, that a learned model used
recursive reasoning, or that performance generalizes beyond this distribution.

## Epistemic-compiler-derived extension

[Truthful selection run 42647776455](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/42647776455)
passed 14 regressions and scored/replayed all 126 scripted answers across 63
finite probability specifications. The new task normalizes selection weights
separately within each world, computes exact posteriors, and reports expected
Brier loss and decision regret separately.

The same literally true message can support different posteriors under
different selection laws. Selection-aware reference answers have zero excess
loss throughout. Content-only forecasts have positive excess loss in all 42
informative cases and decision regret in 19. All 21 uninformative controls
have zero excess and regret. Independent concrete-ticket enumeration agrees
with the posterior in all 63 cases; the suite also tests exact arithmetic,
malformed answers, prior disagreement, and resealed-record corruption.

This implements the bounded truthful-subset and sincere-disagreement roadmap
extensions. OP007 and OP023 retain their prior partial status. These are
scripted controls with disclosed probability laws; learned-model capability,
unknown selection-law discovery, and multi-round interaction remain unmeasured.

An earlier proposed paired teaching-study implementation was stopped by a tool
content filter before any file was written. No specific reason was supplied.
That implementation was not retried and is not part of the executed evidence.

## Evidence and remaining integration work

Downloaded artifacts are under
[`../artifacts/continuation-2026-11-09/hosted/`](../artifacts/continuation-2026-11-09/hosted/).
The recursive artifact contains `production-judge-results.json`,
`production-gate-report.md`, `environment.json`, and all per-case records.
The epistemic artifact contains the prospective design, source hashes,
full records, checksums, TAP log, replay receipt, and exit codes. Adjacent
verification records compare the hosted evidence with the tested Git revision.

The general repository [CI run 42647776312](https://github.com/StrangeTcy/rl_eval_generator/actions/runs/42647776312)
still failed. The failures concern existing environment metadata, campaign
matrix counts, campaign budget bounds, and an API-base assertion. This
continuation does not claim a green repository-wide suite or change those
campaign settings. No model-provider calls or paid inference ran.

The next scientific step for the recursive family is a held-out distribution
and resource-matched comparison with ordinary complete solvers. The next
epistemic step is independent external-policy answers using only the public
packet, preserving raw responses and applying the existing exact scorer.
