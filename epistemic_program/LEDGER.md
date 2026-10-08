# Epistemic Compiler → rl_eval_generator: Program Ledger

Durable handoff ledger for the source-to-implementation program. Updated each batch.

## Revisions

- Source repo: `StrangeTcy/epistemic-compiler`, branch `arena/01a107c8-epistemic-compiler`
- Source revision inspected: `cdd03a2365174250d32b89d970be85bae21c7998` = HEAD of branch
  = the known accepted baseline. **No post-baseline additions exist on this branch**,
  so everything in the corpus is at-or-below the accepted baseline (no "later additions"
  to distrust). Verified: `git merge-base --is-ancestor` → ancestor; HEAD == baseline sha.
- Target repo: `StrangeTcy/rl_eval_generator`, session branch
  `arena/e6e70c43-rl-eval-generator`, base `e1b038a4efb7343afd713f4e981c90fc0fb0485c`
  (single squashed commit in local clone).
- Source checkout kept separate at `/home/user/epistemic-compiler` (read-only use).

## Corpus inventory and read status

### mission-02/sources/ (30 files, ~1.4 MB)

| ID | File | Bytes | Read | Role / preliminary disposition |
|----|------|-------|------|--------------------|
| F01 | 2026-09-29_arena_round_note.md | 9823 | YES | Compiler note on the 09-29 dialogue + Arena round. Verified-vs-not table; "PR1 shipped" claim NOT supported; pilot numbers quarantined. Key: epistemic-trajectories v0.1 track summary; tools/epistemic_probe.py already embodies scripted-target pattern. |
| F02 | 2026-10-02_instruction_revision_note.md | 2743 | YES | Note on raw Arena output (F30). Not executed, not adopted; collides with existing mission state. Disposition: background, do-not-execute. |
| F03 | epistemic_games_dialogue_representation.md | 16386 | headers | Turn-by-turn attribution record for the primary dialogue. Provenance/attribution rules. |
| F04 | epistemic_games_generator_development_paths.md | 5636 | YES | Routing note: 3 independent generator paths (intervention operators / domain variants / episode engine) + separate empirical question. Not an approved architecture. |
| F05 | epistemic_games_genre_index_v2.json | 14272 | headers | Genre catalog index (JSON). |
| F06 | epistemic_games_genre_sorted_v2.md | 236088 | NO (batch B) | Raw genre-sorted dialogue extract v2 (LARGE). |
| F07 | epistemic_games_genre_sorted_v5.md | 220505 | NO (batch B) | Raw genre-sorted dialogue extract v5 (LARGE). Relationship to F06: v5 is a later re-sorting; supersession NOT established by filename alone; both retained. |
| F08 | epistemic_games_genre_v5_01_ideas.md | 17908 | headers | Ideas: Pelevin/reflexive-control/desontology bridge, MI-13, magic/misdirection primitive. Assistant proposals. |
| F09 | epistemic_games_genre_v5_01_ideas_v2.md | 5859 | headers | Disposition register v2 for F08 ideas. |
| F10 | epistemic_games_genre_v5_02_evaluation_experiment_proposals.md | 31589 | KEY parts | Arena synthesis (trajectory = central observable), intervention-operator register (same_fact_presentation / truthful_subset / observation_budget / source_cue / causal_attribution), reporting boundary. Points to docs/epistemic_trajectories*.md (read, see below). |
| F11 | epistemic_games_genre_v5_03_notation_formalism.md | 16480 | headers | Formal core: trajectories + three metrics; notation discipline; semantic quotient σ. |
| F12 | epistemic_games_genre_v5_04_code_drafts.md | 20715 | headers | Code drafts: v0.1 spec materials (overlaps F13). |
| F13 | epistemic_games_genre_v5_05_implementation_generator_specifications.md | 33201 | YES | Generator specs: (1) v2.0 "Epistemic Process Control" spec (grand, unapproved), (2) epistemic-trajectories v0.1 impl spec, (3) six critique changes (no v2.0 rename; strict v0.1 claim; four_way=fixture; structured facts; small primary endpoint; deterministic semantic IDs) + PR order 1–6, (4) actionable spec: exclusion_8x6 primary template, three metrics ℶ/ℷ/ℸ never collapsed, naming lint (presentation ≠ attention), budget sweep {1,2,3}, four validity checks NULL/EFFECT/ABL-1/ABL-2, scripted targets exact_bayesian + bounded(m=3), PR ladder incl. "PR1.5 pilot + four checks". |
| F14–F16 | genre_v5_06_writing_drafts{,_v2,_v3}.md | 63K+58K+44K | NO (batch B) | Writing/blog drafts. |
| F17 | epistemic_games_genre_v5_07_research_prior_art.md | 11952 | headers | Prior-art assessment. |
| F18 | epistemic_games_genre_v5_08_critique_corrections_audit.md | 13822 | headers | Corrections: belief-vs-process boundary, magic foundation, дезонтология correction, causal tests requirement, claims discipline. |
| F19 | epistemic_games_genre_v5_09_context_model_capability_discussion.md | 8677 | headers | Model-news tangent (OpenAI Astra etc.) — background, not eval content. |
| F20 | epistemic_games_hierarchies.md | 13486 | headers+§5 | Hierarchies/recursive structures; §5 user corrections & non-adoption rules (behavior≠mechanism; no single ladder; 15-question portfolio preserved). |
| F21 | epistemic_games_ladders.md | 13055 | YES §1,§10 | Ladder record: E0–E8 ladder = assistant-proposed, UNAPPROVED; belief→process ladder explicitly REJECTED; §10 standing interpretation rules. |
| F22 | epistemic_games_proposed_minimal_test.md | 3510 | YES | Minimal-test candidate (ΔG/ΔQ/ΔR separation; message conditions; A0–A2 as conditions not ladder). Decisions needed before pilot. |
| F23 | epistemic_games_sources_index.md | 22690 | YES | Bibliography/provenance index of dialogue mentions; verification warnings preserved. Category: quoted/external claims. |
| F24 | epistemic_games_without_references_and_hierarchies.md | 226044 | NO (batch B) | Combined dialogue extract (LARGE). |
| F25 | epistemic_trajectories_repo_evolution_battle_prompt.md | 10998 | headers | Battle prompt v1 (methodology artifact). |
| F26 | epistemic_trajectories_repo_evolution_battle_prompt_v2.md | 13157 | headers | Battle prompt v2 with access gate (methodology artifact). |
| F27 | epistemic_trajectories_v2_luna_design_review.md | 2518 | YES | Review: E0–E8 factorization = promising CANDIDATE, not settled architecture; do not promote without adoption + repo audit. |
| F28 | epistemic_trajectories_v2_luna_review.md | 5901 | YES | Review: access receipt matched; attribution error preserved; matched-presentation = candidate operationalization, not approved core. |
| F29 | evolution_responses | 204388 | NO (batch C) | Raw battle-prompt responses (LARGE). |
| F30 | raw/2026-10-02_instruction_revision.gpt_5.6_luna.md | 12734 | via F02 | Verbatim raw output; not adopted. |

### Authoritative context (mission-02, outside sources/)

| Item | Read | Notes |
|---|---|---|
| code snippets critique.md (4463 ln) | STRUCTURE + key rounds | 6 review rounds: gemini-3-flash (CS001–002), gpt6-luna refusal, opus-4.8 retraction, sonnet-5 (CS003–033), grok-4.5 r1 (CS034–066), grok-4.5 r2 (CS067–074), refusal, gemini r2 (CS075–078), **fable-5 final round (CS079–110)** with the complete `shared/epistemic_semantics/*` blueprint, non-negotiable invariants, build order. 110 python blocks ↔ CS001–CS110 confirmed by fence enumeration. |
| initial_code_snippets_proposal_v1.md | part | The critiqued v1 proposal (float Bayes, world-filter PAL, BNE-checker, import-graph V3, text-hash T1). |
| initial_code_snippets_proposal_v2.md | KEY parts | Critique-responsive rewrite: separation of concerns; exact FiniteDist (rejects floats); per-question sections E1–E8/S1–S4/V1–V3/T1; module boundaries + build order mirroring fable-5; integration-point caveats ("verify in the target session before editing"). |
| snippet_reconciliation/approved/ | verified | CS001–CS011: 7 modules (event_bayes, supplied_policy, public_announcements, silence, common_knowledge, epistemic_relations, fragmented_observation) + 11 test files + 11 acceptance records. **82 passed, 37 subtests passed** (re-run here 2026-10-07). Contracts pinned. CS011 record: "User separately requested a new-session prompt to integrate accepted snippets into a new rl_eval_generator environment family; that integration has not run here." → our program IS that integration. |
| gates/question_portfolio_draft.md | YES | E1–E8, S1–S4, V1–V3 definitions + serial development plan (E1 anchor → V3/V1 checks → V2 → S2/S3 → E2–E8 one at a time → S1/S4). All 15 retained by human direction; statuses track progress without pruning. |
| gates/question_cards/E1_supplied_policy_update.md | YES | E1 card: logit response model (β0,β_prior,β_LR)=(0,1,1) target; signed LR (not unsigned R); v0 grid facts; V3 finding (judge not independent), V1 finding (no text→model audit). |
| seed.yaml | part | Mission framing; v0 facts restated; theory pool = leads not evidence; cards frozen before Council. |
| freeze/game_cards.freeze.yaml | part | Freeze bookkeeping for strategy cards. |
| docs/epistemic_trajectories.md, _scope.md, rl_eval_generator_..._proposal.md | YES | Track status: proposed working name; alongside epistemic_games, not a rename; gates before implementation (inspect actual repo first — done here); engine-validated interventions; replay. |
| council/, context/, gates/* (rest), workbench.yaml, retrieval_seed.yaml | NO (batch D) | Council round materials; to be inventoried as provenance, not specs. |

## Target repo inspection (complete for program-relevant seams)

- Registry-driven env families; `generate_env.py` placeholder substitution + opt-in
  deterministic `renderer:` hook (pure fn of subs; sibling imports allowed); baked judge
  files; strict unresolved-placeholder errors; `--difficulty` axis vectors; output dir
  confined to cwd.
- `envs/epistemic_games` v0: verified live — generated an instance (seed 7),
  `tools/public_bayes_oracle.py` solved it from task.md alone (public-info sufficiency),
  judge spec baked with exact posterior. 5 axes → 48 cells.
- `tools/epistemic_probe.py`: verified — baselines (incl. calibrated, seductive,
  framing_sensitive_qNN scripted positives), paired stats, seed-level aggregation.
- Arena layer: `arena.py` subcommands run/trajectory/trajectory-plan/trajectory-analysis/
  summarize/review; `arena/trajectory.py` = direct-answer behavioral probe pattern with
  SYSTEM_ANSWER_ONLY prompts; providers/artifacts/call-guards exist. Model calls NOT
  authorized for this program without explicit permission.
- `envs/trajectory_semantics/*` + `shared/trajectory_semantics`: relay-machine
  solver-synthesis track — UNRELATED to the corpus's "epistemic trajectories" despite
  similar naming. Name-collision noted; do not conflate.
- Tests (local run 2026-10-07): all pass EXCEPT
  (a) `tests/test_campaign_workflow_guard.py::test_a_chained_campaign_presents_a_resume_as_a_resume`
      — pre-existing failure at main HEAD (guard expects text the last atria-campaign.yml
      update removed);
  (b) `tests/test_exhaustive_campaign_recovery.py` — very slow (>120s), not fully run.

## Cross-checks established

1. Approved baseline 82 tests: VERIFIED at source HEAD.
2. CS001–CS011 NOT integrated into target (no counterpart modules).
3. Target v0 epistemic_games matches seed.yaml/E1-card descriptions exactly (priors
   0.5/0.6, R-bands 1/3, 48 cells, weights 0.5/0.3/0.2, strict tol 0.02).
4. "PR1 shipped (arena/epistemic.py)" claim from dialogue is FALSE for target — no such
   file; consistent with F01's "not supported" finding. The presentation/trajectory track
   must be built from scratch (good: also serves as the independent second implementation
   opportunity).
5. Standing rules extracted: no capability ladder; behavior≠mechanism in naming; exact
   Fraction for any categorical label; closed public schemas + GT forbid-list; reject
   non-discriminating instances at generation; provenance ≠ independence; S3 blocked on
   rubric; E6/E8 oracle-before-dataset; T1 separate line; portfolio items stay identifiable.

## Decision log

- 2026-10-07 D1 Foundation batch: **ON HOLD** — user chose "discuss first". Open sub-points
  recorded in "D1 discussion" below; no foundation code written yet.
- 2026-10-07 D2 v0 core: **refactor onto shared bayes NOW** (user overrode the
  keep-untouched recommendation). Constraint I will enforce: observable behavior must stay
  byte-identical (renderer task.md, baked judge spec, grading numerics), proven by a
  differential regression over a seed grid before/after. Known consequence to resolve in
  D1 discussion: core.py is shipped into generated judge images; if it imports
  shared.epistemic_semantics, the layout/Dockerfiles must ship the shared module too.
- 2026-10-07 D3 E-probe shape: **generator env families** (answer-only, v0-style) for
  E2/E3/E4/E5.
- 2026-10-07 D4 T1/presentation pilot: **approved**, offline-only, later batch (after
  foundation/E-families). exclusion_8x6, ℶ/ℷ/ℸ separate, 4 validity checks, budget sweep.
- 2026-10-07 D5 game theory: **E6 only** approved (oracle-first, enumerate-with-reject,
  unique-equilibrium-or-reject, hand-verified fixtures). E7/E8 re-decided later.
- 2026-10-07 D6 pre-existing CI failure: **fix approved and DONE** (see below).

## Implementation log

### Batch 1 — Foundation (implemented 2026-10-07, pending result acceptance)

Scope (user-approved): verbatim vendor of CS001–CS011 + shared exact core + D2
refactor of v0 onto shared bayes + packets/leakage primitives + boundary tests.

What was done:
1. `shared/epistemic_semantics/` package created. The 7 approved modules vendored
   body-byte-identical (verified by epistemic_program/vendor_approved.py; source
   blob SHAs recorded in APPROVED_SOURCES.md); only import lines transformed
   (sibling→relative; tests→absolute). The 11 approved test files vendored to
   tests/epistemic_semantics/ the same way. **82 passed, 37 subtests passed.**
2. `bayes.py` (blueprint layer) wraps/extends approved contracts: re-exports
   FiniteDist/SpecError/calculate_posterior*/SuppliedPolicyInstance/bayes_update,
   adds `posterior_world1` and `likelihood_ratio_band` (v0 bands, exact).
3. `packets.py` (V1): closed PacketSchema with GT forbid-list + validate_packet +
   render_injectivity_probe. `leakage.py` (V2/V1 support): gt_render_forms
   (exact + decimal + percent + complement disguises) + leakage_report.
4. D2 refactor: envs/epistemic_games/files/core.py now takes posterior and
   verdict band from shared.epistemic_semantics.bayes (dual import: repo package,
   judge-shipped package, self-located-root fallback). config.yaml ships the
   package into judge/epistemic_semantics/ only (agent workspace untouched —
   knowledge boundary verified).
5. Differential guard: fixtures/v0_differential.jsonl captured from the
   PRE-refactor core (144 instances = 48 axis cells x seeds 0..2) pinning
   task.md, to_spec(), and 4 grading traces each; test_v0_differential.py
   requires byte-identical regeneration. PASSED after refactor.
6. Boundary tests: LR==3 band edge, asymmetric-prior transposition (band-blind,
   posterior-catching), zero-evidence rejection, float rejection, 1/3 exactness;
   closed-schema unknown/forbidden/missing rejection + injectivity collisions;
   leakage decimal disguises (4/7 vs 0.571), complement leak, no-suppression rule.

Verification evidence (2026-10-07):
- `pytest tests/epistemic_semantics -q`: 243 passed (82 approved + 144
  differential parametrizations + primitive/boundary tests).
- `pytest tests -q` (full suite except slow test_exhaustive_campaign_recovery):
  all pass, including the D6-fixed workflow guard (6/6).
- Generation smoke (report,strong,paired,skewed,bare_table seed 3): judge/
  epistemic_semantics shipped; agent workspace contains 0 shared files;
  tools/public_bayes_oracle.py solved the task from task.md alone
  (posterior 3/31, verdict distinguishable).
- Judge-container simulation: fresh interpreter, sys.path=[generated judge/] →
  `import core`; rebuilt spec == baked INSTANCE_SPEC; grade(ground truth)=pass.
- tools/epistemic_probe.py runs unchanged on the refactored core.

Source units addressed by Batch 1: CS001–CS011 acceptance records (vendored);
critique final-round shared primitives bayes/packets/leakage (CS079/CS103/CS104
lineage, wrapped-not-replaced per approved-contract rule); proposal v2 "shared
exact arithmetic"; E1-card signed-LR note (documented in bayes.py); standing
rules (exactness, closed schemas, GT forbid-list, behavior-only naming).

### Batch 2 — E-line generator families E2/E4/E5/E3 (implemented 2026-10-08, pending result acceptance)

Scope (user-approved via D3 + batch authorization): E2/E3/E4/E5 as generator
environment families (answer-only, v0-style), not arena probes. All four
families consume ONLY the accepted shared substrate from Batch 1 and ship it
judge-side only (agent workspace contains 0 shared files, verified).

What was done:
1. `envs/epistemic_announcements/` (E2, sequential PAL). Axes: worlds
   {three,four} x depth {one=exactly 1, chain=realizes 2–3, capped by
   n_worlds−1 informative steps} x query {factual=atomic matched control,
   nested} x scenario {expedition,office}. Consumes CS005
   public_announcements. Certificates: (a) truncation-flip on NESTED queries
   only — factual controls are depth-invariant BY DESIGN because atom truths
   survive every truthful restriction, so the depth contrast lives across the
   query axis; (b) public derivability fairness invariant — the registered
   question must be constant across all worlds surviving the full transcript
   (otherwise no reasoner could answer from public information and accuracy
   would measure luck). Rejection sampling over derived seeds `{seed}:{attempt}`.
2. `envs/epistemic_nested_knowledge/` (E4, knowledge order). Axes: worlds
   {four,six} x order {first=K_i p, second=K_i K_j p, third=bounded K_i K_j
   K_i p} x scenario {expedition,office}. Consumes CS002/CS005. Task shape is
   NAMED-TARGET model checking (the evaluated scenario is public), since
   hidden-actual nested queries are not publicly answerable. Certificate: the
   named scenario must have a same-valuation twin at which the registered
   formula flips (generation biases valuations toward twins). Worlds axis is
   four/six because measured per-attempt discrimination rates at three worlds
   are ~0.5–2.9% (structurally near-unreachable for third order) vs
   ~6.5–41% at four/six; MAX_ATTEMPTS=256 bounds per-cell failure near 1e-8.
3. `envs/epistemic_fragmented_observation/` (E5, observation matrices). Axes:
   worlds {four,six} x fragment {symmetric=shared partition, asymmetric=
   distinct partitions} x scenario {expedition,office}. Consumes CS005 + CS011
   fragmented_observation (joint_information). Registered propositions are
   about the pooled cell; named-target shape. Certificates per level:
   asymmetric → pooled set is a PROPER subset of each individual cell
   (pooling strictly informative); symmetric → the named scenario's own facts
   do not decide the payload (some cell member evaluates it differently).
   CS011 boundary honored in task semantics: pooling is cell intersection,
   not communication; no individual/common knowledge claims.
4. `envs/epistemic_silence/` (E3, silence vs matched message). Axes:
   observation {silence,message} x protocol {single,pair} x prior
   {uniform 1/3, skewed 1/2-1/4-1/4} x scenario {expedition,office}. Consumes
   CS007 silence + CS003/CS008 supplied_policy (bayes_update) + CS001
   event_bayes. THREE worlds because deterministic rules over two worlds admit
   only degenerate (0/1) informative posteriors. Answer = exact rational
   posterior of scenario one + direction (increased/decreased/unchanged).
   Certificates: realized event mass strictly in (0,1) and posterior differs
   from prior. Spec records the matched counter-observation posterior
   (judge-side only) for research contrast. Grading failure modes:
   pass / wrong_magnitude / wrong_direction / wrong_posterior /
   answer_format_invalid.
5. Shared scaffolding mirrored from the v0 family: per-env renderer baking
   TASK_MD + JUDGE_INSTANCE, instance_spec.py provenance rebuild contract,
   v0-style judge.py (patch/source validation → rebuild == baked spec →
   bounded literal ANSWER extraction → binary grading), visible_tests.py
   (format-only, template-passing), answer.py, Dockerfiles, config.yaml with
   judge-only `epistemic_semantics/` layout. Registry: 4 new entries
   (envs/registry.yaml lines 38–41).
6. Scoring: new mode `exact_classification` (binary exact match; no
   thresholds by design) registered in tests/test_scoring.py with an
   explicit documented branch. This is a documented extension of the scoring
   guard, not a change to existing modes.

Verification evidence (2026-10-08):
- Family suites: E2 9 tests, E4 7, E5 7, E3 7 — all pass (30 tests). Coverage:
  full deterministic grids (96/72/48/96 cells), certificates recomputed
  independently from the spec through the accepted substrate, ground-truth
  recomputation, public-task knowledge boundary (no ground-truth fields or
  values in task.md), binary grading, unknown-axis ValueError, spec rebuild.
- `pytest tests -q` (full suite except slow test_exhaustive_campaign_recovery):
  all pass, including the documented exact_classification guard extension.
- Generation smoke for all four families via generate_env.py: judge bundles
  shipped (CS005+CS002 / +CS011 / CS007+CS003+CS001 respectively); agent
  workspace contains 0 shared files; visible_tests pass on the shipped
  template answer.
- Judge-container simulation (fresh interpreter, sys.path=[generated judge/])
  for all four families: rebuild == baked INSTANCE_SPEC; grade(ground
  truth)=pass; wrong-answer grading verified (wrong_truth / wrong_magnitude).

Consequential design decisions taken inside the approved batch (disclosed for
acceptance review): (D-E2) flip certificate applies to nested queries only,
factual controls depth-invariant by design; public-derivability invariant.
(D-E4) named-target task shape; worlds axis four/six (empirically justified).
(D-E5) named-target shape with per-level certificates. (D-E3) three-world
models (empirically justified); exact-fraction answers. All families are
answer-only and make no mechanism claims beyond the accepted substrate's own
documented boundaries.

Source units addressed by Batch 2: portfolio questions E2/E4/E5/E3 (feasibility
rules honored: bounded finite models; no common-knowledge or general
theory-of-mind claims); approved substrate consumption matrix: E2→CS002/CS005,
E4→CS002/CS005, E5→CS005/CS011, E3→CS001/CS003/CS007.

### Batch 3 — V1/V3 verification track (implemented 2026-10-08, pending result acceptance)

Scope (user-approved roadmap): V1 (faithfulness of English renderings) and
V3 (feasibility of independent verification) as operational, offline checks
for the four E-line families. Per the portfolio, V1/V3 are supporting
measurement-validity / engineering-feasibility checks, not LLM outcome
hypotheses; no model calls are involved.

What was done:
1. `tools/epistemic_verifier.py` — independent verifier. Parses each family's
   public task.md (structural line parsers + recursive-descent parser over
   the public formula grammar: atoms, "it is not the case that", "X knows
   that", "pooling ... pins down that") and:
   - V1 mode: reconstructs the registered formal state (valuation,
     partitions/observation matrices, announcement sequence or announcement
     rules, target scenario, registered proposition, prior) and exact-matches
     it against the judge-side spec fields. Predefined treatment: any parse
     mismatch is recorded as a faithfulness failure with an error type;
     annotation is mechanical, no adjudication step.
   - V3 mode: recomputes ground truth from the parsed public text using ONLY
     the accepted shared substrate (CS005 PAL, CS011 joint_information,
     CS007 silence, CS003/CS008 supplied policy, CS001 event Bayes). The
     tool imports no family core.py and reads no generator logic. Notably,
     the E2 ground truth is recomputed WITHOUT the hidden actual world:
     announcement-by-announcement restriction plus the public-derivability
     invariant (query truth constant across the final survivors) — a
     strictly weaker-information path than the judge's.
   Surface-vocabulary tables are mirrored DATA (agent-visible strings only,
   no generation/grading logic), pinned against drift by a test.
   CLI: `python tools/epistemic_verifier.py --dir <generated env> --mode both`
   with exit code 0/1; corrupt inputs report structured failures instead of
   crashing.
2. `tests/test_epistemic_verification.py` — 6 tests:
   - structural independence guard (verifier source imports no family core,
     never calls build_instance);
   - vocabulary drift pins (E2 prefix / E4-E5 exact / E3 exact);
   - V1 exact reconstruction over full grids, 156 instances
     (48 E2 + 36 E4 + 24 E5 + 48 E3, seeds 0-2): 156/156 exact;
   - V3 independent verification over the same 156 instances: 156/156
     verified against baked specs;
   - tamper detection (renamed world, deleted partition block, corrupted
     prior all caught — the verifier is not a rubber stamp);
   - CLI end-to-end on a real generated environment, including a corrupted
     copy flipping the exit code.

Verification evidence (2026-10-08):
- `pytest tests/test_epistemic_verification.py -q`: 6 passed.
- `pytest tests -q` (full suite except slow test_exhaustive_campaign_recovery):
  exit 0 (361 tests).
- CLI exercised inside the end-to-end test on a generated epistemic_silence
  environment: v1 exact_reconstruction=true, v3 verified=true on the
  pristine artifact; verified=false (structured failure) after corruption.

V3 feasibility conclusions recorded per family (portfolio asks for a check,
not a full external verifier): all four families support a verifier that
does not share the generator implementation, because (a) every registered
formal component is rendered as uniquely parsable public text, and (b) the
accepted substrate suffices to recompute the intended answer from that text
alone — for E2 even without the hidden actual world. The intended local
extension (this verifier) is described within the available architecture:
it is a repository tool consuming only public artifacts and shared modules.

Source units addressed by Batch 3: portfolio section C (V1, V3; V2 remains
queued per roadmap — it is a retrieval precondition for the S-line, not an
E-line dependency); dependency-plan steps 2 and 7 (assess V1/V3 on the
substrate families; repeat where families change formal or rendering
assumptions — the four Batch-2 families are all covered).

## D6 fix record (2026-10-07)

- Failure: tests/test_campaign_workflow_guard.py::test_a_chained_campaign_presents_a_resume_as_a_resume
  at main HEAD. Root cause: the last main commit ("Update atria-campaign.yml") replaced the
  workflow-level `GITHUB_EVENT_NAME` override (presenting a chained resume as 'schedule')
  with a child-process `env -u GITHUB_EVENT_NAME` on the resume-gated branch plus explicit
  `--allow-provider`. This matches the hardened controller (`_should_reset_output` refuses
  destructive inferred fresh without --fresh; docstring: "the lesson is not 'fix the event
  name'"). The guard test asserted the OLD mechanism verbatim.
- Fix: rewrote that test to assert the semantic safety property — a chained resume must
  reach the controller without GITHUB_EVENT_NAME=workflow_dispatch — accepting either (1)
  the env override (chained example source of truth) or (2) the resume-gated unset branch
  (deployed workflow), with ordering checked. No workflow file changed; the user's latest
  atria-campaign.yml intent is preserved.
- Evidence: verified deployed file uses unset-mechanism only, chained example uses
  override-mechanism only; `pytest tests/test_campaign_workflow_guard.py` 6 passed; all
  other test files pass (slow test_exhaustive_campaign_recovery.py still not run to
  completion — >120s).

## D1 discussion (RESOLVED 2026-10-07 — approved as refined)

Sub-decisions surfaced for the user:
1. Vendor policy for CS001–CS011: verbatim copy into shared/epistemic_semantics/ with a
   provenance manifest (module → acceptance record → critique line range) vs adapted
   rewrite vs spec-and-reimplement. My recommendation: verbatim (contracts frozen; CI only
   runs pytest so no lint conflict; approved tests are already pytest-compatible).
2. Overlap rule: approved modules vs fable-5 blueprint modules (e.g. event_bayes vs
   bayes.py core): approved code may be wrapped/extended by blueprint modules, never
   silently replaced or semantically altered without explicit approval.
3. D2 shipping detail: core.py importing shared.epistemic_semantics requires the generated
   judge workspace/image to ship the shared module (layout entries + Dockerfile/sys.path),
   mirroring how shared/patch_validator.py is shipped. Alternative: keep core.py
   self-contained in the family (violates single-source-of-truth). Recommendation: ship
   the shared module into judge/ via layout.
4. Test placement: approved + new tests under tests/epistemic_semantics/ (pyproject
   testpaths=["tests"]).

## Next action

Batch 1 + D6 fix: ACCEPTED and committed/pushed as `f1e552a` (verified on
origin 2026-10-07).

Batch 2 (E2/E4/E5/E3 families): ACCEPTED 2026-10-08 and committed/pushed as
`e901cbc` (verified on origin). Working tree: envs/registry.yaml, tests/test_scoring.py,
envs/epistemic_announcements/, envs/epistemic_nested_knowledge/,
envs/epistemic_fragmented_observation/, envs/epistemic_silence/,
tests/test_epistemic_announcements.py, tests/test_epistemic_nested_knowledge.py,
tests/test_epistemic_fragmented_observation.py, tests/test_epistemic_silence.py.

Batch 3 (V1/V3 verification track) awaits result acceptance and commit/push
authorization. Working tree: tools/epistemic_verifier.py,
tests/test_epistemic_verification.py, epistemic_program/LEDGER.md.

After authorization and commit: Batch 4 (T1 presentation pilot, offline-only,
user-approved in D4) per roadmap. Parallel
reading backlog: F06/F07/F24/F29 large dialogue extracts, F03/F05/F08–F12/
F14–F19 deep reads, council/context/freeze triage, proposal-v2 per-question
sections, critique mid-round details (for the source-to-code matrix rows of
CS012–CS110 dispositions).
