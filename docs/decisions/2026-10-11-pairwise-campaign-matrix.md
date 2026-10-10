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

## 5. Not done: interventions in the campaign lane

`--interventions` stays out of the paid campaign. `tools/family.py` is the lane that owns it,
because a twin must be **generated and `twin_check`ed against bytes before any model is
contacted** — otherwise "the agent was invariant" cannot be distinguished from "the
intervention did nothing". The campaign's manifest path can carry declarations only
(`suite_inventory`'s own words: *"Declarations are carried, not verified"*). Three of 39
environments implement any intervention today. Cheapest useful step, no campaign change:
run `tools/family.py --check` for those envs at the vectors a campaign would bill, and let a
future preflight admit only the verified ids.
