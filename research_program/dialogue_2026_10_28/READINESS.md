# Readiness and validation

> Runtime update, 2026-10-28: [109 hosted tests passed](RUNTIME_VALIDATION.md), including all mapped tests for the 28 covered OP entries. Implementation completeness remains 15 source-implemented and 13 partial. The pre-runtime account below is preserved as historical evidence; its statements about tests being unexecuted are superseded by the linked execution record. Broader experiment and integration gaps remain.


**Current state: source implementation reviewed; tests authored; runtime unverified.** No repository code, new environment, model evaluation, package installation, or test suite was executed after reading the mission's execution restriction. Initial shell reads loaded the mission attachment and existing notes before that restriction was known; subsequent work used file APIs only. No suitable isolated execution runner is exposed by the available tools.

## Authored checks

The regression suite is `tests/test_inquiry_games.py`. Its purpose is to validate scientific and protocol boundaries, not merely duplicate implementation details.

| Gate | Evidence authored | Status |
|---|---|---|
| Exact conditioning | Hand-derived posterior `1/9,0,2/3,2/9`; impossible-event rejection. | Not run |
| Query value | Complementary tests reduce four-state risk from `3/4` to `1/2` then `0`; explicit cost/stop/horizon examples. | Not run |
| Prior dependence | Independent partition-risk values `2/5` and `3/10` under weights `4,3,2,1`. | Not run |
| Independent reference | Public-text solver using unnormalized weights; diagnostic/source trials and corrected-evidence comparison. | Not run |
| Role boundary | Public views and semantic identities invariant to private world seeds; controller initialization not echoed. | Not run |
| Presentation validity | Duplicate/omitted rows, extra prose, repeated presentation, and first-row controls. | Not run |
| Incentive reversal | Low/high audit reversal; exact tie at audit `2/3` with gain `4`, fine `2`. | Not run |
| Ambiguous causes | Positive-report posterior `1/5` sincere error versus `4/5` strategic; subsequent high-audit posterior `3/19` versus `16/19`. | Not run |
| Literal truth | Assertion/certificate twins share reports and posterior, with certificate literal-falsehood probability zero. | Not run |
| Protocol counterfactual | Blind response law is unchanged; disclosed high audit changes the strategic bad-quality response. | Not run |
| Recovery | Reveal only after a report, at most once; posterior incorporates independent final quality. | Not run |
| Parser/judge attacks | Invalid probability sums, NaN, zero denominators, repeated/exhausted queries, post-terminal actions, extra/missing replay actions. | Not run |
| Transport | EOF remains unscored; bounded interaction; separate sender result. | Not run |
| Always-distrust rival | False certainty about intent receives loss when no misleading event occurred. | Not run |

## Required isolated checks before use

1. In an authorized isolated checkout with Python 3.11 or newer, run only the new standard-library test module using `python -m unittest discover -s tests -p test_inquiry_games.py -v`. This command is a future instruction and has not been run. Record Python version, exact file hashes, command, exit status, and full output. Focused `unittest` discovery avoids the repository's pytest completion hook described below.
2. Generate a wider finite matrix across semantic/private seeds, budgets, prior regimes, source channels, visibility, and noise. Compare the independent public oracle to the engine and preserve every disagreement. Do not silently change fixtures to agree.
3. Check the complete source and diagnostic action trees, including early stopping, impossible observations, zero-cost tests, exact ties, repeated source probes, and all presentation permutations.
4. Verify transcript replay from private controller configuration and raw **valid actions**, then separately verify error/response ordering in recorded trial events. Score reconstruction is not proof of policy provenance.
5. Exercise an external-process transport with trusted controller initialization separated from the agent stream. An in-process `Trial` is only for trusted scripted policies.
6. Before any provider pilot, specify role prompts, budget/call bounds, held-out cases, pairing and invalid-output policy, and inspect the complete public observations. Provider calls still require separate authorization.

The code is deliberately not wired into the ordinary generated-workspace registry or an existing automatic campaign. That prevents an unverified interactive track from being treated as another ready patching environment.

## Import and runner findings

Importing `arena.inquiry` first loads `arena/__init__.py`, which imports `arena/providers.py` and then `arena/secrets.py`. The inspected chain uses standard-library imports; `datetime.UTC` in `providers.py` requires Python 3.11 or newer. Top-level initialization constructs an HTTP opener, resolves candidate credential-file paths, and compiles redaction patterns. The inspected top-level code does not call provider completion or load credential-file contents. Import success has not been verified by execution. The new package itself adds no credential lookup or provider invocation; the inherited import chain is still part of its runtime boundary.

`conftest.py::pytest_sessionfinish` calls `tools/campaign_kick.py::maybe_kick_from_ci`. With an eligible campaign instruction and CI context, that existing code can obtain a job credential and request workflow dispatch. Therefore ordinary repository pytest in CI is not the proposed isolated readiness route. Use focused `unittest` discovery, which does not load `conftest.py`; review any alternative harness before using it. No CI action, hook, campaign-state change, or credential resolution was initiated during this work.

## What static review supports

The formulas can be inspected: diagnostic values include a stop option, costs, and remaining horizon; source actions derive from the stated audit payoff; all categorical thresholds use exact fractions; public renderers exclude latent seeds and oracle values. The independent reference has no import from the games or finite calculus. These are source findings, not executed outcomes.

Static review cannot establish import/collection success, transport behavior, finite-matrix coverage, hidden-case accuracy, runtime complexity in the installed environment, or model performance. The source inventory and file hashes establish which artifacts were inspected, not that the software passed its gates.
