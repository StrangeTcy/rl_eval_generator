# Campaign matrix: `covering` (t=1) → optional `pairwise` (t=2 + uniform ladder)

Date: 2026-10-11. Status: **landed on this branch as an opt-in mode; no live profile changed.**

## 1. What was wrong

`tools/suite_inventory.py` offered three expansion modes. The campaign profiles used
`covering`, which is **one-factor-at-a-time**: a base vector at each axis's first level,
plus one vector per remaining level varying a *single* axis (`1 + Σ(levels−1)`). Its
docstring claimed coverage, and coverage is what it delivers — but with no two axes ever
moving together, a two-axis interaction is not under-sampled, it is **unobservable**. The
name "covering" borrows from *covering arrays*, which are strength ≥ 2 by definition.

There was no written rationale anywhere for stopping at t=1 while `all` (the full product,
9,318 vectors at seed 0) sat behind a guard. The only trace of intent is budget arithmetic
computed *from* the 241-case plan: `limits.max_api_calls: 10050` ≈ 241 × 40 calls plus
headroom, `max_tokens_total: 66000000`.

## 2. The numbers that decide it

Repo estimator: 40 calls / 327,680 tokens per case (`run_suite._estimated_case_budget(20, 8192, 1)`);
gated = cases in the 12 environments with an exact-instance oracle reference.

| design | vectors | gated | paid ceiling | gate wall (worst-case guard) |
|---|---|---|---|---|
| `covering` (t=1) | 241 | 96 | 9,640 calls / 79 M tok | 173 h |
| **`pairwise` (t=2 + ladder)** | **358** | **131** | **14,320 calls / 117 M tok** | **236 h** |
| `all` | 9,318 | 8,373 | 372,720 calls / 3.05 B tok | 15,103 h |

The gate, not the model bill, is what prices a matrix: at 2,100 s per judge variant,
`all` is 8,373 rows of oracle work before one paid call. Pairwise is 1.5× today for the
strongest claim the suite can make.

## 3. Decision

`pairwise` is added as a fourth mode and as a campaign-selectable `matrix.mode`; `covering`
remains the default so every in-flight resume keeps its case ids. A profile switches by:

```yaml
matrix: {mode: pairwise, seeds: [0]}
limits: {max_api_calls: 15400, max_tokens_total: 100000000}   # 358 cases × 40, +7 %
```

Never flip modes mid-campaign: case ids are `{env}__{vector}__seed-{n}`, so a new mode is a
new plan and banked gate rows/episodes do not carry over.

## 4. Two fail-closed preflights this interacted with

* `atria_campaign._validate_campaign_profile` hard-required `matrix.mode: covering`.
  Relaxed to `{covering, pairwise}`; `all` and `representative` stay refused for paid lanes.
* `_apply_gate_blocked_exclusions` raised if any reviewed `manual_gate_blocked_exclusions`
  id was absent from the manifest — and **all 7** are t=1 single-axis spikes that pairwise
  does not generate, so a mode switch killed the campaign at startup. Absence is now split:
  an id whose *environment* is in the manifest but whose vector is not, is recorded under
  `manual_gate_blocked_exclusions_not_enumerated` (nothing to omit); an id naming an
  environment the manifest lacks is still a hard error, so typos and profile drift keep
  failing closed. The post-omission level-coverage check is mode-agnostic and passes both ways.

## 5. Interventions: billable, but only where a twin proves the claim

An earlier reading of this repo said "three of 39 environments implement any
intervention". Measured against the manifest the campaign builds, it is **four**
environments and **eight** ids, and the expansion is bigger than that suggests:

```
epistemic_games 24   glyph 30   moco 75   css_state_machine 9      = 138 twin cases
iids: terminology 39, visible_proxy 30, evaluator 15, retrieval_cue 15,
      reward_proxy 15, evidence 8, presentation 8, prior 8
pairwise 358 -> pairwise + interventions 496 vectors, 269 reference-backed
```

So `matrix.interventions: true` is now a profile key, threaded into
`suite_inventory.build_manifest(expand_interventions=...)`, and paid cases carry the
intervention in their identity (`run_suite` already passed `--interventions` to
generation and included it in the episode id).

What was *not* negotiable is verification. `tools/family.py` proves an overlay by
comparing base and twin bytes **before** a model is contacted; the manifest path only
carries declarations. So the controller runs `tools/twin_preflight.py` after writing
the manifest and before any provider call, grouping cases by (environment, vector,
seed) so one `family.py` call verifies every twin sharing a base - 47 calls, 20 s,
no network.

Measured verdicts on this manifest: **79 pass, 33 fail, 26 unverified**. Hence three
policies, and the campaign default is the middle one:

| mode | behaviour |
|---|---|
| `strict` | refuse to start if any billed twin did not verify |
| `bill_verified_only` | drop non-verifying twins, name them in `intervention_twin_omissions`, bill the rest |
| `advisory` | bill everything, label the rows |

`off` is **refused** whenever `interventions: true`: the one failure mode this whole
layer exists to prevent is an inert overlay being read as model-level invariance.

26 of the 138 fail for a reason internal to the checker rather than to the overlay:
`ENV_NAME` is on its `blocked_placeholders` list, so the generated
`ENV_NAME="<member>"` line - the *only* difference outside the intended files for a
pure rename - cannot be normalized, and `only_the_instance_label_differs` stays
false. Normalizing that line (or not embedding the member name in it) is the
follow-up that would let this campaign move to `strict`.

## 6. Resuming a covering campaign into a pairwise one

The intuition "pairwise subsumes covering, so the new campaign can resume the old
one" is true of *levels* and false of *cases*:

```
covering vectors                       241
pairwise vectors                       358   (496 with intervention twins)
vectors present in both                142   (59%)
covering vectors that pairwise drops    99   <- the single-axis spikes, incl. all 7
                                                manual_gate_blocked_exclusions ids
pairwise vectors that are new           216
covering gated rows inside this plan     40   of 96
```

So a mode switch is not a resume: the episode ledger, the campaign intent and the
terminal markers all belong to the campaign that made them, and 99 verified
instances of the old plan are simply not part of the new one.

What *can* cross the boundary is the exact-instance gate row cache, because
`run_suite` keys a row on `case_sha256` - the content hash of that case - and
accepts it only when the file's `gate_context_sha` equals the current revision
(`git rev-parse HEAD`). Nothing about that pair of keys mentions the plan.
`tools/inherit_campaign_state.py` therefore filters the old campaign's rows to the
cases this plan bills, and refuses the whole carry - rather than rewriting
`gate_context_sha` - when the two campaigns sit on different commits. Rewriting it
would accept a verdict produced by different grading code, which is the exact thing
the guard exists to prevent. T1's report follows the same revision rule, with an
explicit `--allow-cross-revision-t1` opt-in recorded in the report.

The consequence is operational and unavoidable: **the richer campaign inherits
anything only once both campaigns run the same commit.** A resumed campaign checks
out the ref recorded in its own state artifact, so the live covering runs stay
pinned where their 72 banked rows were validated; a pairwise campaign necessarily
starts at a newer tip (it needs the mode to exist). Inheritance pays in the one
sequence that aligns them - re-pin the covering campaign at the new tip, let its
gate phase re-bank rows there, then launch the pairwise campaign - and it is the
`gate_rows_status: refused_gate_context_differs` line that makes the other case
legible instead of a silent re-gate of 40-odd rows.
