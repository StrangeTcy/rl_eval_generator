# Approved source artifacts (CS001–CS011) — vendor manifest

**Source repository:** `StrangeTcy/epistemic-compiler`
**Source branch:** `arena/01a107c8-epistemic-compiler`
**Source revision:** `cdd03a2365174250d32b89d970be85bae21c7998` (= HEAD = accepted baseline)
**Source paths:** `mission-02/snippet_reconciliation/approved/<file>` and the
`CS*_acceptance.md` records beside them.
**Vendored:** 2026-10-07, via `epistemic_program/vendor_approved.py` (kept in-repo
so the vendoring step is reproducible and auditable).

## Transformation rule (the ONLY change applied)

Bodies are byte-identical to the accepted artifacts (verified per-file by the
vendoring script, which strips import lines from both sides and compares the
rest, and records the source git blob SHAs below). Only import lines changed:

1. Intra-package sibling imports became relative imports
   (`from event_bayes import X` → `from .event_bayes import X`) so the package
   works both as `shared.epistemic_semantics` in this repository and as
   `epistemic_semantics` when shipped into generated judge images.
2. Test imports became absolute (`from supplied_policy import X` →
   `from shared.epistemic_semantics.supplied_policy import X`); `import silence`
   → `from shared.epistemic_semantics import silence`.

## Modules (accepted contracts — frozen)

| File | Source blob | Acceptance record | Question |
|---|---|---|---|
| event_bayes.py | 38ad4bb36c48b71724da8c7bdb010f9d2d466ac3 | CS001_acceptance.md | E1 event-based Bayes; sparse + strict contracts |
| supplied_policy.py | 4be2578958ec2c68d63419e5131610dfe689d052 | CS003–CS006 acceptance records | E1 full-policy interface |
| epistemic_relations.py | 718eea53f1bc618abc6705cb681af5147c6f5fcd | CS002-related (Sonnet E2 substrate) | E2/E4/E5 S5 relations |
| public_announcements.py | c2162722196e1c849f5b227cc428ae49316d0a8d | CS007/CS008 | E2 model restriction + knowledge eval |
| silence.py | 129d5f9f5d541ed1c3ba9d3f477ff17651e11e0b | CS009/CS010 | E3 speech policy + silence update |
| common_knowledge.py | 2d310e2dcfbef63f4a022ca59c9fa913ad0fa77f | CS010-era (common-knowledge source tests) | E2/E4 common knowledge |
| fragmented_observation.py | 26f8e98895577ac1dd00560092e5ae71daec6776 | CS011_acceptance.md | E5 partitions/joint information |

## Tests (accepted suites — frozen bodies)

| File | Source blob |
|---|---|
| test_event_bayes.py | 5c6a3b2b9cb8c7278f606c887219c2c42ef755a4 |
| test_supplied_policy.py | 2a73c368ab532d336f15c11fa3ffa22fa95b2888 |
| test_epistemic_relations.py | d077729943b67f4a0ae5eef470611c330036044c |
| test_public_announcements.py | 78a5297ffe3da24e70e16296ef584602507d0e92 |
| test_silence.py | 223eb0c1d59ce17d8ea34f076753eba62d5999e3 |
| test_common_knowledge.py | 57bb885a82d8beb681c0fa67e7f3300623b51aa4 |
| test_fragmented_observation.py | 77657cd448723d74de110ac09eb9a23419e51612 |
| test_source_e1_fixtures.py | 48736ff3297ccf23a5170cc2b1f8244f0a221e0a |
| test_source_e2_fixtures.py | c99bc338fc0d69b2bf53f5a6b13b7a6d52a25a0c |
| test_source_e3_fixtures.py | 73bd3452f877a35563d98b156a3ce6efd329f6ca |
| test_source_e4_fixtures.py | f39f47a790d0407b8e27a021a39244be713d20ee |

## Verification status

- At vendor time: all 18 files body-identical (script output: ALL BODIES IDENTICAL).
- Baseline suite re-run in this repo: **82 passed, 37 subtests passed**
  (`pytest tests/epistemic_semantics`), matching the recorded baseline.
- Re-verification against the source repo at any time:
  `python3 epistemic_program/vendor_approved.py` (read-only comparison mode
  re-derives the report; the source checkout must exist at
  `/home/user/epistemic-compiler` or the SRC path must be adjusted).

## Contract rule

Accepted modules are frozen. Later code may import, wrap, or extend them; it
must never silently replace them or change their semantics without explicit
user authorization (applies in particular to unaccepted blueprint snippets
CS012–CS110 from `mission-02/code snippets critique.md`).
