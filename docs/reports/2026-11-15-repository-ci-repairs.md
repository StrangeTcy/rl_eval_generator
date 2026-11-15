# Repository CI repairs — 15 November 2026

The audit-repair and causal-family branches still exposed nine repository-wide
pytest failures. This change addresses the underlying plan and runtime defects;
it preserves the existing paid-campaign ceilings.

## Frozen legacy campaign membership

The original pairwise campaign was created at
`b56e33a76a0adc12b62d72a77cebad91bfdddb5d` with 39 environments: 358 baseline
cases and 138 intervention twins, giving 496 cases. Eleven environments were
subsequently added to the repository. Unconditionally scanning every config
enrolled 100 additional pairwise cases and 77 additional covering cases in the
old profiles. That expansion exceeded their existing refusal thresholds.

The four legacy Mercury/Atria covering/pairwise profiles now explicitly select
the original 39-environment cohort. The shared inventory remains unrestricted
when no cohort is supplied. Campaign execution, checkpoint inheritance, and
budget checks consume the same selection. The manifest records the cohort
identity, and malformed, unknown, missing, or mismatched entries are rejected.

The resulting pairwise plan has 496 cases before existing exclusions and 482
afterward. The covering plan has 241 before exclusions and 233 afterward. The
historical covering count of 234 preceded the later reviewed RoPE exclusion.
All HTTP, call, token, step, and retry ceilings remain unchanged. The added
environments remain available for separately designed campaigns.

## Endpoint and T1 identity

Commit `11bef46` deliberately routed the reasoning Atria pairwise profile through
`https://discovery-api.intern-ai.org.cn/v1`, while the legacy controller and its
T1 profile still required the older endpoint. The named pairwise campaign now
pins the Discovery route explicitly and references a separately named matching
T1 profile. That T1 counterpart preserves the model, reasoning mode, wire API,
case matrix, and 72-call planning ceiling.

The historical covering and T1 profiles keep their recorded endpoint identity.
Unknown endpoints and mismatched campaign/T1 identities continue to fail
validation. This configuration repair makes no provider request and does not
resolve the provider's separate `429 quota_exceeded` response. Existing
checkpoints remain tied to their recorded source and measurement contract.

## Recursive runtime repairs

- The distributed capacity example acquires the root permit before spawning.
  One permit then prevents the child from completing; two permits allow it.
  This restores the intended structural capacity distinction.
- Maze replay and search require a cleared child before exiting only when
  remaining nesting depth is positive. At depth zero, another descent is
  forbidden, so shafts cannot also seal the exit permanently. The public prompt
  now states this boundary.

These are minimal edits over the tested branch. Broader recursive work already
present in the shared checkout is preserved. No `core.py` is changed.

## Verification record

The dedicated `Repository regression repair checks` workflow validates the
matching T1 plan without provider access and reruns the nine recorded failures.
The repository-wide CI separately runs the full pytest suite and Docker smoke
builds. Hosted outcomes are recorded after execution; this document does not
claim a pass before those jobs finish.

Local Node checks verify cohort provenance and arithmetic. Python checks run
on GitHub. Reproducible overlays and publication metadata are retained in
`runs/repository-ci-repairs-2026-11-15/`.
