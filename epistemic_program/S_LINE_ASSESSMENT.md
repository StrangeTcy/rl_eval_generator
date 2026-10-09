# S-line scope assessment (Batch 6, 2026-10-08)

Durable assessment of the strategy-pack questions S1–S4 for the
source-to-implementation program. This is a verification artifact: every
status below is grounded in corpus text (epistemic-compiler @
`cdd03a2365174250d32b89d970be85bae21c7998`) plus inspection of the target
repository. Nothing here implements an S-card; implementation requires an
explicit user decision per question.

## Corpus grounding

* `mission-02/gates/question_portfolio_draft.md`, section B: S1–S4 question
  statements, discriminators, competing predictions, nearest collisions,
  feasibility notes, and scope limits. The draft marks them "distinct
  causal questions; a positive answer to one does not imply a positive
  answer to the others."
* `mission-02/code snippets critique.md`, sections "S1 — card content
  versus generic advice" through "S4 — transfer across epistemic families":
  per-question snippet assessments, scientific/architecture gaps, correct
  implementation boundaries, and statuses.
* Dependency plan (portfolio draft): S2 then S3 on an established substrate
  family; S1 separate from S2; S4 after at least two family cards have
  stable semantics and supporting checks; V2 is the retrieval precondition
  for any trigger-matching claim.

## What Batches 1–5 already supply (verified in target)

1. **Frozen task families with stable semantics**: five generator families
   now exist and are registered (E1-equivalent v0 `epistemic_games`, E2
   `epistemic_announcements`, E4 `epistemic_nested_knowledge`, E5
   `epistemic_fragmented_observation`, E3 `epistemic_silence`) plus E6
   `epistemic_type_games`. Every generated spec already carries
   generation-time identity tags: `family` and `question` keys in every
   `to_spec()` output (verified in all six family cores). This is exactly
   the critique's "label-only utility" for S2 — the label side costs
   nothing further; it exists.
2. **Paired-arm data structures** (Batch 4, T1 pilot):
   `shared/presentation_identity.py` provides deterministic matched-arm
   construction with generation-time identity (`MatchedFactPair`,
   `build_matched_fact_pair`, content-based IDs). It covers the "same
   instance, varied one thing" data shape the critique lists as shared
   primitive #4. What it does NOT provide is prompt-level arm assembly
   (`Arm.prompt_supplement`) or cross-arm orchestration.
3. **Deterministic seeded generation + provenance**: every family builds
   reproducibly from `(axes, seed)` and ships a baked spec the judge
   rebuilds — the substrate S-line arms would reuse unchanged.
4. **Independent verification**: `tools/epistemic_verifier.py` (V1/V3) can
   certify instance artifacts across all six families — relevant later as
   the "same oracle scoring" requirement for any arm comparison.

## Per-question status

### S1 — value of method text beyond generic advice

* Portfolio: paired correctness difference (card vs length/format-matched
  generic method instruction) on one frozen family.
* Critique status: arm-construction utility = `implementable primitive`;
  the S1 question itself = `needs prior-art/source check first` on what
  "generic advice" should contain so the comparison is fair (Self-Discover,
  Buffer of Thoughts etc. are leads).
* Target readiness: family substrate ready (pick one frozen family);
  arm orchestration missing (prompt assembly + solver runs + paired
  statistical comparison). Solver runs are model calls — not authorized
  for this program without explicit permission.
* Blockers: (a) prior-art/source check on the generic-advice content;
  (b) authorization for model calls if/when the trial is to be executed.

### S2 — incremental value of trigger matching

* Portfolio: trigger-matched card vs yoked non-matching same-family card,
  card count/format/exposure controlled; trigger defined from information
  available BEFORE solver output; card/matcher must not see answers or
  validity labels.
* Critique status: transcript matcher = NOT implementable as scored code
  yet (keyword matching is a gameable proxy; needs a gold-labeled
  calibration set + inter-rater agreement — the V2 validation debt);
  generation-time family tagging = `implementable primitive` — ALREADY
  SATISFIED in the target by the spec `family`/`question` tags.
* Target readiness: label side done; matcher side deliberately absent.
* Blockers: V2 prerequisite (characterization reliability + leakage audit)
  and a gold-labeled calibration set; then a methodology decision about
  the matcher.

### S3 — incremental effect of obligations

* Portfolio: same-card with-vs-without validity-obligations contrast on
  trigger-present but move-invalid instances.
* Critique status: `currently too underspecified` — no agreed written
  rubric exists in the corpus; any checker would encode an unvalidated
  guess. The critique explicitly proposes NO code and says the next step
  is authoring `gates/s3_rubric.md` plus two independent human annotations
  on a calibration set. Answer-correctness and justification-validity must
  remain separate scores, never silently summed.
* Target readiness: none; correctly so.
* Blockers: rubric authorship (a spec artifact + human annotation). This
  matches the roadmap entry "S3 blocked."

### S4 — transfer across epistemic families

* Portfolio: held-out-family accuracy for a card authored on another
  family with the same declared structural feature; transfer defined
  before outcomes; exploratory, "do not add it silently to the current
  seed."
* Critique status: analysis-only, and only after S1-style paired-arm
  infrastructure exists; must control matched surface difficulty (partial
  correlation or equivalent), otherwise surface co-variation masquerades
  as conceptual transfer.
* Target readiness: two-or-more stable family semantics now exist (the
  dependency-plan precondition), but the paired-arm + analysis layer does
  not.
* Blockers: S1 infrastructure; difficulty-matching controls; prior-art
  check for transfer claims (portfolio: broad transfer claims are not
  registered in the current seed).

## Verified non-actions (things deliberately NOT done)

* No transcript matcher shipped (S2): would encode a gameable proxy as a
  scored metric without a gold set — exactly the failure the critique
  flags.
* No validity-obligation checker (S3): would encode an unauthored rubric
  as settled methodology.
* No transfer metric (S4): would report an uncontrolled association.
* No model calls anywhere: S-line execution needs solver runs, which are
  not authorized for this program.

## Options for the user (decision requested)

1. **Hold the S-line at assessment status** (recommended default): leave
   S1–S4 queued with these documented blockers; continue with other
   approved tracks. Costs nothing; preserves every constraint.
2. **Author offline S-line specifications only**: write the S1
   generic-advice contrast spec and the S3 rubric DRAFT as gate-style spec
   documents (no code, no model calls), so the human-annotation steps can
   start. Still requires the user's prior-art direction for S1's generic
   advice content.
3. **Build the offline arm-construction primitive now** (critique shared
   primitive #4, prompt-level `Arm`/`arm_seed`), explicitly UNUSED until
   model-call authorization exists. Small, reversible, spec-faithful.
4. **Authorize a model-call pilot** for one frozen family (would be a new
   authorization beyond current decisions; requires explicit scope:
   provider, budget, and which arm comparison).

Statuses recorded here persist in the ledger's source-to-code matrix.

## Addendum (2026-10-08): option c executed

User decision: option c accepted. The offline prompt-level arm-construction
primitive is now implemented at `shared/experiment_arms.py`
(`Arm` / `build_paired_arms` / `arm_seed`, corpus shared primitive #4):
data construction only - no model calls, no network, no scoring. A boundary
test (`tests/test_experiment_arms.py`) enforces that no environment, judge,
renderer, or tool consumes it while model calls remain unauthorized.
Execution of any S1/S4 comparison still requires the explicit model-call
authorization described in option 4 above.
