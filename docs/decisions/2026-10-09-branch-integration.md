# Branch integration: `arena/e6e70c43` (epistemic-semantics program) onto `arena/3fd95b93` (causal-experiment layer)

Date: 2026-10-09. Status: **additive port landed and green; conceptual reconciliation proposed, awaiting approval.**

## 1. Why this is not a `git merge`

The two branches have **no common ancestor** (`git merge-base` is empty). Current
`main` is `93cbb48` "Add files via upload" — a fresh snapshot that already contains
the causal-layer lineage (PR-A/PR-B: `twin_check`, `family`, `evaluator_views`,
`generation_manifest`, `trajectory_metrics`, `interventions.yaml`, `ev_base`/`ev_twin`,
the `.patch`). `arena/e6e70c43` is rooted on `e1b038a`, the *older* main that the
"Add files via upload" orphaned; `e1b038a` shares no ancestor with `93cbb48`, and the
two roots differ by 69 files / ~19.5k lines.

Consequence: integration is a **content-level port** (`git checkout <their-ref> --
<paths>` to extract their blobs into this tree), not a merge. `main` already equals the
causal-layer lineage, so this branch (`b81c49d`) is the sensible trunk and their work is
ported onto it (user decision).

## 2. What each branch is

| | `arena/3fd95b93` (this trunk) | `arena/e6e70c43` (ported from) |
|---|---|---|
| Theme | Causal-experiment layer | Epistemic-semantics program |
| Adds | latent registry (`pair_id`/identity), `information_policy` replay, twin families, measurement adversary, shortcut gate | `shared/epistemic_semantics/` exact-semantics substrate, **5 new env families** (`epistemic_type_games`, `_silence`, `_nested_knowledge`, `_fragmented_observation`, `_announcements`), `presentation_identity`, `experiment_arms`, `arena/result_record`, independent `epistemic_verifier` (V1/V3), `epistemic_program/` ledger |

## 3. Additive port landed this session (user chose "additive-first")

Ported (90 files) — the dependency-closed additive set the 5 families need:

- `shared/epistemic_semantics/` (12 files) — referenced by 28 of their family/test files; hard dependency.
- `envs/epistemic_{type_games,silence,nested_knowledge,fragmented_observation,announcements}/` (50 files).
- `tests/epistemic_semantics/` (17) + `tests/test_epistemic_{type_games,silence,nested_knowledge,fragmented_observation,announcements}.py` (5).
- `epistemic_program/` (5) — required by `tests/epistemic_semantics/test_v0_differential.py`.
- `envs/registry.yaml` — their version (purely additive: 5 new env entries; identical base, untouched by this trunk).

Conformance fixes required to make their `e1b038a`-era families work under this trunk's generator:

1. **`latent_factors:` blocks added to all 5 new configs** via `tools/latent_factors_scaffold.py --all --write` (PR-C.1 made the block mandatory; theirs predate it). Registry is now **39/39**; the 5 new blocks are stamped `scaffold_unreviewed`.
2. **`envs/epistemic_silence/config.yaml`: prior-axis level `balanced` → `uniform`.** Their config declared a `balanced` level its own core (`PRIORS_BY_AXIS` = `{uniform, skewed}`) rejects — a copy-paste from `epistemic_games`. Their own test already used `("uniform","skewed")`. Caught by this trunk's `oracle_preflight` gate (never run on their branch).
3. **`tests/test_scoring.py`: added the `exact_classification` mode branch** (all 5 families use it). This is verbatim their clean, self-contained edit to a file identical across both bases.
4. **`tests/test_latent_registry.py`: made the registry-count assertions count-agnostic** (`N/N`, `stamped == len(paths)-1`) so the test survives registry growth (34 → 39, and more during reconciliation) while preserving intent (every config valid; exactly one hand-authored).
5. **`tests/epistemic_semantics/test_v0_differential.py::test_shared_core_is_the_refactored_source_of_truth` skipped** with a reason pointing at §5. The other 145 tests in that file pass, including all 144 byte-identical differential guards — which *proves their `core.py` refactor is behavior-preserving* (this trunk's un-refactored `core.py` reproduces their captured fixture exactly).

Verification after the additive port: full `pytest tests/` = all pass except the **known pre-existing** `test_campaign_workflow_guard::test_a_chained_campaign_presents_a_resume_as_a_resume` (documented under PR-B.4 as landing separately against `main`, not here) and the 1 deliberate skip above. `oracle_preflight` = **0 failures** across all 39 envs (5 new families generate + compile). `suite_inventory` = 39 cases, `registry_clean`, `ready_for_scheduler`. `latent_factors_scaffold --check` = 39/39.

## 4. Deferred to the reconciliation step (not ported)

- **The 3 `epistemic_games` overlap files**: their edits to `config.yaml` (ships a `judge/epistemic_semantics/` package), `files/core.py` (refactor to delegate to the shared substrate), `files/judge.py` (`stage_outcomes` structured records). These collide with this trunk's `information_policy` work and PR-D plans.
- **Overlap-mechanism modules + their tests**: `shared/presentation_identity.py`, `shared/experiment_arms.py`, `arena/result_record.py`, `tools/epistemic_verifier.py`, `tests/test_{presentation_identity,experiment_arms,result_records,epistemic_verification}.py`.
- **`stage_outcomes` plumbing**: their `shared/patch_validator.py` (`PatchValidationError` with a `.code` — additive, backward-compatible) and `shared/judge_lib.py` edits; tied to `result_record`.
- **Diverged-base files**: `arena.py`, `arena/episode.py`, `tools/run_suite.py` (this trunk's base has PR-B changes their root lacks — need 3-way reconciliation).
- **`tests/test_campaign_workflow_guard.py`**: their branch modifies it (may already carry the one-line resume fix this trunk was told to leave for a separate PR to `main` — must not be done twice).

## 5. Reconciliation proposal — "one mechanism each" (awaiting approval)

Reading their modules, most overlaps are **different layers that compose**, not duplicates. The only true single-source-of-truth consolidation is the Bayes math. Proposed mapping (nothing deleted until approved):

| Concern | Theirs | Mine | Proposal (canonical → what happens to the other) |
|---|---|---|---|
| **Bayes core / verdict bands / policy tables** | `shared/epistemic_semantics/` (`bayes`, `event_bayes`, `supplied_policy`) — accepted formal substrate | `information_policy._record()` recomputes bands by hand from `core.EVIDENCE_TABLE`; PR-D would expand `core.py` inline | **One source: `shared/epistemic_semantics`.** Adopt their behavior-preserving `core.py` refactor (delegate to shared `bayes`), re-point `information_policy._record()`'s band/policy math at the shared substrate, un-skip the bridge test. `supplied_policy` (formal probability-table policy) and `information_policy` (judge-replay selection *contract*) then layer cleanly: the contract consumes the semantics. |
| **Task identity** | `presentation_identity.py` — *intra-instance* fact-object identity for matched-fact presentation arms (T1) | `latent_spec` identity projection / `pair_id` — *registry-wide instance* task identity across twins | **Both kept; different granularity.** `latent_spec` stays canonical for instance identity/`pair_id` (the 5 families already got `latent_factors` blocks). `presentation_identity` stays for fact-level arms inside the epistemic families. Optional: share one canonicalization helper (`latent_spec.canonical_json`) so there's a single hashing convention. |
| **Verification / faithfulness** | `epistemic_verifier.py` (V1/V3) — *independent* recomputation from public text + shared substrate, never importing family `core.py` | judge re-derivation (shares `core`) + `information_policy` replay — runtime provenance / anti-tamper | **Both kept; complementary.** Their verifier is the offline *independence/faithfulness* audit; my replay is the *runtime reward gate*. Cross-wire: the verifier can audit `epistemic_games` and my `information_policy` record as one more faithfulness target. |
| **Structured records** | `arena/result_record.py` + judge `stage_outcomes` — *run-time* per-attempt/per-stage outcomes | `generation_manifest` / `latent_spec` — *generation-time* provenance + identity | **Both kept; different lifecycle.** Merge only at the `epistemic_games/judge.py` overlap: `stage_outcomes` recording and my `information_policy_ok` check coexist (my check can also emit a stage outcome). Adopt their `PatchValidationError(code)` so stage statuses are machine-readable. |

Net: **one deletion-class consolidation** (fold the Bayes-band math into `shared/epistemic_semantics`), everything else is layering with documented boundaries. The largest concrete task is the 3-way reconciliation of `epistemic_games/{config.yaml,core.py,judge.py}` (their semantics refactor + `stage_outcomes` ⟕ my `information_policy` + latent_factors), which also unblocks PR-D on the shared substrate.

## 6. Suggested next step

On approval of §5: (a) reconcile the 3 `epistemic_games` files (adopt their `core.py`→shared-`bayes` refactor, merge `stage_outcomes` with the `information_policy` replay gate, keep both layout additions), (b) re-point `information_policy._record()` at the shared substrate and un-skip the bridge test, (c) port `result_record`/`presentation_identity`/`experiment_arms`/`epistemic_verifier` + their tests, 3-way the diverged `arena.py`/`episode.py`/`run_suite.py`, (d) resolve `test_campaign_workflow_guard` once (check whether their edit already is the PR-B.4 fix), (e) full suite + tools green, commit, push.

## 7. Reconciliation executed (§5 approved by the user)

**Phase 1 — the one consolidation (Bayes math → `shared/epistemic_semantics`).** Landed as commit `eb4deed`:
adopted their behavior-preserving `core.py` D2 refactor (posterior + verdict band delegate to
`bayes.posterior_world1` / `bayes.likelihood_ratio_band`); merged their judge-shipment of the
`epistemic_semantics` package into `config.yaml` alongside this trunk's `judge/information_policy.py`;
**folded `information_policy._record()`'s hand-rolled band math into `core._semantics_bayes.likelihood_ratio_band()`**
(reached through `core` because the policy's own purity contract forbids importing `sys`/`pathlib`,
which a direct three-context fallback would need); merged their `stage_outcomes` record on the
judge's patch-validation path (coexists with the `information_policy` replay gate — different regions);
adopted `PatchValidationError(code)` and `judge_lib`'s `_FAILURE_STAGE`/`_mark_stage` (so `reward_denial`,
including the policy gate, is machine-readable registry-wide); un-skipped the differential bridge test.

**Phases 2–3 — the kept layers + diverged-base wiring.** The four overlap modules are self-contained
(`result_record` → `deepcopy` only; `presentation_identity`/`experiment_arms` → stdlib only;
`epistemic_verifier` → the already-ported `epistemic_semantics`), so they ported as clean additions with
their tests (`presentation_pilot.py` came along as a test dependency). The diverged-base files were
3-way merged (`git merge-file`, base `e1b038a`): `arena.py` clean; `tools/run_suite.py` clean (their
`_build_command` id-threading is purely additive and every name it references already exists in this
trunk's runner); `arena/artifacts.py` adopted wholesale (identical base); `arena/episode.py` had **one**
conflict — my base added `"interventions": interventions` to the oracle-case dict while theirs improved
`case_id` to `options.case_id or options.episode_id or "direct"` — resolved by **combining both** (their
`case_id` + my `interventions`); `--case-id` is defined in the cleanly-merged `arena.py`.

**Phase 4 — `test_campaign_workflow_guard` (NOT ported; standing instruction).** Their branch does *not*
touch the workflow; it relaxes the *test* to accept a second resume mechanism — `env -u GITHUB_EVENT_NAME`
on a resume-gated branch — and **this trunk's deployed `atria-campaign.yml` already uses exactly that**
(`env -u GITHUB_EVENT_NAME python tools/atria_campaign.py`, lines 658–661). Adopting their test edit would
make the guard pass, i.e. would "fix the campaign guard on this branch," which the user's standing
instruction forbids (it lands as its own PR against `main`). So the guard is **left failing here**.
Consequence for that separate PR: the recorded PR-B.2/B.4 plan (add a `GITHUB_EVENT_NAME: ${{ … 'resume' … }}`
step override — mechanism 1) is likely **superseded** — the deployed workflow already moved to mechanism 2,
and the only thing failing is the old test's refusal to recognize it. The separate PR should choose between
(a) their test-side acceptance of mechanism 2 (no workflow change) and (b) the original mechanism-1 workflow
override, not do both. Flagged for the user; not decided here.

**Boundary note (kept layers, not unified):** `presentation_identity` (intra-instance fact identity for
matched-fact arms) and `latent_spec` (registry-wide instance identity / `pair_id`) coexist at different
granularities; `epistemic_verifier` (independent offline faithfulness, never imports family `core.py`) and
the judge's re-derivation + `information_policy` replay (runtime provenance/anti-tamper) coexist as
complementary verification layers; `result_record`/`stage_outcomes` (run-time) and `generation_manifest`/
`latent_spec` (generation-time) coexist across lifecycles. The only true single-source-of-truth merge was
the Bayes math (Phase 1). No mechanism was deleted.
