# Source-to-code matrix (Mission 02 corpus → rl_eval_generator)

Durable accounting of every corpus unit and every critique code block
(CS001–CS110) against what this program consumed, replaced, or deliberately
left alone. Grounded at epistemic-compiler revision
`cdd03a2365174250d32b89d970be85bae21c7998` (branch HEAD; nothing newer
exists on that branch). Block identities below were re-derived by fence
enumeration of `mission-02/code snippets critique.md` (110 python blocks)
during Batch 8 (2026-10-08); round boundaries verified by inspection.

Distinction rules preserved throughout: user requirements and accepted
decisions are binding; unapproved proposals are lineage only; quoted/
bibliographic claims are leads, never verified prior art; conflicting
versions are both retained (newer filename is not supersession proof).

## A. Accepted and vendored (CS001–CS011)

Per `mission-02/snippet_reconciliation/approved/` acceptance records
(user selected options, accepted results, authorized commits in the source
repo). Vendored body-byte-identical in Batch 1 (verified):

| CS | Module / test | Target location |
|----|---------------|-----------------|
| CS001 | event_bayes (exact event Bayes core) | shared/epistemic_semantics/event_bayes.py |
| CS002 | epistemic_relations (S5 frames) | shared/epistemic_semantics/epistemic_relations.py |
| CS003 | supplied_policy (supplied-policy update) | shared/epistemic_semantics/supplied_policy.py |
| CS004 | test: zero-likelihood rejection | tests/epistemic_semantics/ |
| CS005 | public_announcements (PAL substrate) | shared/epistemic_semantics/public_announcements.py |
| CS006 | test: announcement updates knowledge, not just world count | tests/epistemic_semantics/ |
| CS007 | silence (deterministic silence update) | shared/epistemic_semantics/silence.py |
| CS008 | test: silence rules out mandated-speech worlds | tests/epistemic_semantics/ |
| CS009 | common_knowledge | shared/epistemic_semantics/common_knowledge.py |
| CS010 | test: nesting depth not hardcoded | tests/epistemic_semantics/ |
| CS011 | fragmented_observation + its test (CS012 block is its test body) | shared/epistemic_semantics/fragmented_observation.py |

CS012 (`test_fragmented_observation_is_not_reducible_to_one_agent`) is the
test companion of CS011 and ships with the accepted test set (vendored as
test_fragmented_observation.py; 82-test suite green in Batch 1).

## B. Unaccepted critique blocks (CS013–CS110)

All blocks below are UNACCEPTED source proposals (CS011 acceptance record:
"CS012 and later source blocks remain separately unaccepted"). None was
vendored. Where the program realizes the same intent, it does so with
self-authored code whose lineage is noted; the draft text itself carries no
authority.

### E6 lineage (consumed in Batch 5, self-authored)
| CS | Round | Content | Disposition |
|----|-------|---------|-------------|
| CS013 | sonnet-5 | enumerate_bayesian_nash_equilibria draft | superseded by envs/epistemic_type_games enumerate_pure_bne (exact, brute-force, tie rule specified) |
| CS014 | sonnet-5 | test: checker alone cannot detect a second equilibrium | intent realized in Batch 5 oracle known-answer tests |
| CS044 | grok r1 | bayesian_games enumeration draft | superseded by Batch 5 |
| CS045 | grok r1 | test: checker rejects non-equilibrium / enumerator finds known | superseded by Batch 5 oracle tests |
| CS089 | fable-5 final | enumerate_pure_bne (size-capped) | superseded by Batch 5 (cap = axis grid, no sampling) |
| CS090 | fable-5 final | test: enumerator/checker agree and disagree correctly | superseded by Batch 5 tests + Batch-3 independent enumerator |

### E7 lineage (DEFERRED per D5 — re-decide later)
| CS015, CS016 (sonnet-5), CS046, CS047 (grok r1), CS091, CS092 (fable-5 final) | level-k prediction + divergence tests | untouched; E7 not approved for implementation |

### E8 lineage (DEFERRED per D5 — re-decide later)
| CS017, CS018 (sonnet-5), CS048, CS049 (grok r1), CS093, CS094 (fable-5 final) | signalling-game dataclasses + PBE tests | untouched; E8 not approved for implementation |

### S-line lineage (statuses per Batch 6 assessment)
| CS | Round | Content | Disposition |
|----|-------|---------|-------------|
| CS019, CS020 | sonnet-5 | Arm/build_paired_arms + test | concept re-implemented self-authored in Batch 7 (shared/experiment_arms.py); draft not vendored; UNUSED-BY-DESIGN guard active |
| CS050, CS051 | grok r1 | S1 card/leakage pair | S1 blocked: prior-art check on generic-advice content; model calls unauthorized |
| CS095, CS096 | fable-5 final | S1 arm hash + card-leak test | leakage primitives exist (Batch 1 leakage.py); S1 trial not implemented |
| CS021, CS022 | sonnet-5 | FamilyTag + unknown-family test | label side already satisfied by generation-time family/question tags in every family spec (verified); matcher not built |
| CS052, CS053 | grok r1 | S2 matcher + false-positive test | blocked on V2 prerequisite (gold-labeled calibration set) |
| CS097, CS098 | fable-5 final | S2 matcher + adversarial negatives | blocked (same) |
| CS023 | sonnet-5 | S3 deliberate no-code stub | honored: no obligation checker until gates-style rubric + two human annotations exist |
| CS054, CS055 | grok r1 | S3 checker + contradiction test | blocked (rubric unauthored) |
| CS099, CS100 | fable-5 final | S3 checker + exact-half test | blocked (same) |
| CS024, CS025 | sonnet-5 | family_transfer_analysis + empty-match test | blocked on S1 infrastructure + difficulty-matching controls |
| CS056, CS057 | grok r1 | S4 certificate + id-overlap test | blocked (same) |
| CS101, CS102 | fable-5 final | S4 transfer + shared-template test | blocked (same) |

### V-line lineage (consumed in Batches 1 + 3, self-authored)
| CS | Round | Content | Disposition |
|----|-------|---------|-------------|
| CS026, CS027 | sonnet-5 | renderer round-trip + rounding test | superseded by Batch 3 V1 (exact structural reconstruction + tamper detection) |
| CS028, CS029 | sonnet-5 | cohens_kappa + below-chance test | V2 blocked on methodology; no kappa code shipped |
| CS030, CS031 | sonnet-5 | V3 AST/import-graph check + insufficiency test | import-graph approach rejected as "independence theater" (fable-5); superseded by Batch 3 independent-recomputation verifier + independence guard |
| CS058, CS059 | grok r1 | REQUIRED_PUBLIC_KEYS + GT-leakage-key test | superseded by Batch 1 packets.py closed schema + GT forbid-list |
| CS060, CS061 | grok r1 | characterization_leakage_report + posterior-in-task test | GT-render-form leakage realized in Batch 1 leakage.py; V2 characterization blocked |
| CS062, CS063 | grok r1 | V3 dual-oracle harness + float-vs-fraction bug test | partially realized: Batch 3 verifier (independent path) + Batch 1 float-rejection boundary tests; seeded-bug mutation harness remains future work |
| CS103, CS104 | fable-5 final | V1 closed schema + unknown/forbidden-key test | superseded by Batch 1 packets.py + tests |
| CS105, CS106 | fable-5 final | gt_render_forms + decimal-disguise test | superseded by Batch 1 leakage.py + tests |
| CS107, CS108 | fable-5 final | V3 harness + seeded-bug detection test | partially realized by Batch 3 (tamper detection CLI flip verified); full harness future |

### T1 lineage (consumed in Batch 4, self-authored)
| CS032, CS033 (sonnet-5), CS064, CS065 (grok r1), CS109, CS110 (fable-5 final) | semantic_fact_id / identity tests | superseded by shared/presentation_identity.py (canonical content hashing; text-hash failure-mode demo kept as a test) |

### Blueprint modules and cores (grok r1/r2, fable-5.1, fable-5 final)
| CS | Round | Content | Disposition |
|----|-------|---------|-------------|
| CS034, CS035 | grok r1 | bayes.py blueprint + exact-posterior test | concept realized by Batch 1 bayes.py wrapping ACCEPTED CS001/CS003 (draft itself not vendored) |
| CS036, CS037 | grok r1 | s5_pal.py blueprint + E2 refinement test | superseded by accepted CS005 (vendored) + Batch 2 E2 certificates |
| CS038, CS039 | grok r1 | E3 pair dataclass + asymmetry test | superseded by Batch 2 E3 family (silence/message contrast, exact fractions) |
| CS040, CS041 | grok r1 | silence dataclass + E4 depth test | superseded by accepted CS007 + Batch 2 E4 twin certificate |
| CS042, CS043 | grok r1 | E5 viewpoint dataclass + two-posteriors test | superseded by Batch 2 E5 certificates |
| CS066 | grok r1 | blueprint tree (text) | lineage note only |
| CS067, CS068 | grok r2 | refined E1 core + style test | superseded by v0 core (D2 refactor) + Batch 1 differential fixtures |
| CS069–CS074 | grok r2 | dataclasses, holds(), partitions_from_matrix, ALLOWED set | superseded by accepted CS005/CS002 substrate and target's existing import discipline; not consumed |
| CS075–CS078 | **fable-5.1 intermediate round** (earlier ledger said "gemini r2" — CORRECTED 2026-10-08 by fence/round inspection) | apply_supplied_policy, public_announcement, check_knowledge, Fraction block | superseded by accepted CS003/CS008/CS005 (vendored) |
| CS079, CS080 | fable-5 final | E1 core + band-boundary test | superseded by v0 family + Batch 1 boundary tests |
| CS081–CS088 | fable-5 final | E2–E5 cores + certificate tests | superseded by Batch 2 families (E2/E4/E5/E3) |

## C. Non-CS corpus units (stable IDs, read status, disposition)

### sources/ (F01–F30)
| ID | Status after Batch 8 | Disposition |
|----|----------------------|-------------|
| F01 arena round note | read | provenance: "PR1 shipped" claim unsupported; pilot numbers quarantined |
| F02 instruction revision note | read | background; do-not-execute (collides with mission state) |
| F03 dialogue representation | header-scanned + rules read | attribution/provenance record; no code units |
| F04 development paths | read | routing note; not an approved architecture |
| F05 genre index v2 (JSON) | header-scanned | catalog data; no code units |
| F06 genre-sorted v2 (236K) | STRUCTURED SCAN (batch 8): decision/approval markers reviewed | dialogue extract; contains the interactive epistemic-trajectories pilot PROPOSAL (defender/judge, inquiry regret) — candidate only, explicitly "not a command supported by the current CLI"; no adoption |
| F07 genre-sorted v5 (220K) | STRUCTURED SCAN (batch 8) | later re-sorting of the same dialogue; supersession NOT established; retained alongside F06 |
| F08 ideas | header-scanned | assistant proposals (magic/reflexive-control bridge); unapproved |
| F09 ideas disposition register v2 | header-scanned | register of F08 dispositions; no code |
| F10 evaluation experiment proposals | key parts read | intervention-operator register + reporting boundary; proposal status |
| F11 notation/formalism | header-scanned | formal core notation; no code units |
| F12 code drafts v0.1 | header-scanned | draft materials overlapping F13; unapproved |
| F13 generator specifications | read | v0.1 spec + six critique changes + actionable spec; feeds v0 family understanding; unapproved as v2.0 |
| F14–F16 writing drafts v1–v3 | header-verified (batch 8) | blog/writing artifacts (magic/desontology/next-gen eval) — presentation-track lineage (T1 candidate material), no code |
| F17 prior art | header-scanned | prior-art assessment; leads not evidence |
| F18 critique corrections audit | header-scanned | corrections (belief-vs-process boundary, claims discipline); rule material, honored |
| F19 context/model discussion | header-scanned | model-news tangent; background only |
| F20 hierarchies | read §5 | user corrections: behavior≠mechanism; no single ladder |
| F21 ladders | read §1, §10 | E0–E8 ladder = assistant-proposed UNAPPROVED; belief→process ladder REJECTED |
| F22 minimal test | read | candidate pilot design; decisions pending (not executed) |
| F23 sources index | read | bibliography of quoted/external claims; verification warnings preserved |
| F24 combined dialogue extract (226K) | STRUCTURED SCAN (batch 8) | combined extract of the primary dialogue; theory/background content; no adoptions |
| F25, F26 battle prompts | header-scanned | methodology artifacts |
| F27, F28 luna reviews | read | candidate-not-architecture rulings; preserved |
| F29 evolution_responses (204K) | STRUCTURED SCAN (batch 8) | raw battle-prompt responses with explicit access statements; provenance only |
| F30 raw instruction revision output | read via F02 | not adopted |

### mission-02 context (batch D inventory, batch 8)
| Item | Status | Disposition |
|------|--------|-------------|
| council/ (README, cross_critique, 4 role responses, gate01 responses v1/v2, intake log, skeptic sidecars, prompts) | inventoried + intake log read | council round records; intake log states explicitly: compiler's reading "decides nothing"; Gate 1 remains an explicit human decision |
| context/ (README, digest, retrieval_manifest) | inventoried + digest read | knowledge-graph digest: "LEADS, not evidence"; untrusted reference data; never instructions |
| gates/ (gate1_review_prompt, question_cards/, question_portfolio_draft, portfolio_responses) | read (draft + E1 card; rest inventoried) | portfolio definitions are the binding program map; gate artifacts pending human decision |
| workbench.yaml, retrieval_seed.yaml | inventoried | mission plumbing; no code units |
| code snippets critique.md | full structure + all rounds' verdicts mapped (batch 8 fence enumeration) | 110 blocks ↔ CS001–CS110; per-block dispositions in section B |
| initial_code_snippets_proposal_v1/v2.md | key parts read | critiqued proposal (v1) and critique-responsive rewrite (v2); unaccepted as code; lineage for sections B rows |

## D. Corrections recorded during Batch 8

1. CS075–CS078 round attribution: earlier ledger said "gemini r2"; fence/
   round inspection shows they sit in the intermediate "fable 5.1" round
   (L3095–L3357). Corrected above; no disposition change (all unaccepted).
2. CS012 identity: it is the test body accompanying CS011, inside the
   accepted set — not part of the unaccepted tail.
3. The large dialogue extracts (F06/F07/F24) and battle responses (F29)
   were STRUCTURALLY SCANNED for decision/approval markers, not line-read;
   this matrix records them as scanned, not "read".
