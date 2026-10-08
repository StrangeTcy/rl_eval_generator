# Generator upgrade: 27 proposals, reviewed against the code

Status: **all 27 recorded — 16 from part 1 (items 1–16) + 11 from part 2 (P2.1–P2.11), all
`CONFIRMED`.** Each answer is recorded verbatim in *Answers*; the resulting build order is in
*Build order*. **PR-A is implemented** (see *PR-A: what landed* at the end of this file);
PR-B…PR-E are not.
Repository revision reviewed: `e1b038a4efb7343afd713f4e981c90fc0fb0485c` (`main`), branch `arena/81157642-rl-eval-generator`.
Method: every proposal below was checked against the actual generator, registry, judge library,
suite tooling and test suite at that revision. The two upstream analyses also cite
`epistemic-compiler` files and the 156-node / 452-edge research graph; **neither is present in this
checkout**, so anything involving them is specified as a file contract, not an import.

## Census (the numbers the plan has to respect)

| Measurement | Value |
|---|---|
| `envs/**/config.yaml` environments | 34 |
| Total difficulty axes across all configs | 97 |
| Configs declaring `renderer:` (procedural instance generation) | **1** (`epistemic_games`) |
| Configs declaring `oracle:` | **1** (`epistemic_games`) |
| Configs declaring `benchmark:` | 3 |
| Artifacts written by `generate_env.py` | templated files only — **no manifest** |
| Envs with a re-derivable latent spec (ground truth computed by the judge) | **1** (`epistemic_games`, `Instance.to_spec()`) |
| Existing matched-control machinery | 1 track only (`arena/trajectory_runner.py`) |

Consequence that shapes everything below: an *intervention* in this repo is not a new capability —
it is the **existing axis mechanism** (a `%%PLACEHOLDER%% → value` mapping, optionally with a
`layout:` override) carrying a declared equivalence class. What 33 of 34 envs cannot support is the
tier that needs a second valid oracle (evaluator / reward substitution). Sequencing follows that
asymmetry, not the other way round.

Sandbox constraints found while reviewing: `torch` is not importable here, so `shared/judge_lib.py`
cannot load and no Docker-based judge path can be exercised in this environment; verification for
the layers below must be model-free and torch-free (`generate → diff → compile → structural
compare`), which is also what makes them CI-safe.

Pre-existing, unrelated to this document: `pytest -q` at HEAD fails
`tests/test_campaign_workflow_guard.py::test_a_chained_campaign_presents_a_resume_as_a_resume`
because `e1b038a` added the `Chain the next dispatch` step to the live
`.github/workflows/atria-campaign.yml` without the `GITHUB_EVENT_NAME` resume override the guard
requires (the same file's comment at line 110 says the chained variant must not be copied).
**Decision: leave untouched in this branch**, noted in the PR description.

## Decision log

| # | Proposal | Verdict | Cost | Answer |
|---|---|---|---|---|
| 1 | Every env is a causal intervention family | mechanism exists; add declared overlay + family object | M | **CONFIRMED · hybrid** — global id taxonomy in `envs/interventions.yaml`, per-env implementation; unimplemented id = compile-time error |
| 2 | Explicit counterfactual twins | highest value, mechanically checkable at generation time | M | **CONFIRMED · structure + delta** — `twin_check` canonicalized-tree equality, then score AND normalized-answer comparison; `pair_id = sha256(latent_spec)`, fallback recorded |
| 3 | Difficulty vector → intervention vector | accept, but reclassify existing axes rather than run a parallel taxonomy | S | **CONFIRMED · reclassify** — `class:` on existing axes; `--interventions` for new overlays only |
| 4 | First-class latent-variable layer | already real in 1 env; generalize instead of inventing | M | **CONFIRMED · require all 34** — `latent_factors:` declared in every config (overrides the recommended "required only where procedural") |
| 5 | Misleading but internally consistent worlds | types 1–2 exist as prose masks; type 3 needs a shipped policy module | L | **CONFIRMED · policy module** — deterministic `information_policy` module under the renderer-hook contract, judge re-runs it |
| 6 | Same answer, different required computation | already built for the direct-answer track; patch envs only admit a weak proxy | M | **CONFIRMED · both, proxy first** — interaction-depth proxy on the 33 patch envs now; one matched-answer family on the trajectory_semantics engine as a separate step |
| 7 | Shortcut-policy generation | 4 hand-authored shortcuts already sit in `examples/`; promote to a gated artifact | M | **CONFIRMED · curated + blocking** — `envs/<env>/shortcuts/*.patch` with authored per-evaluator expectations; `tools/shortcut_gate.py` blocks CI where the judge imports without torch, nightly Docker elsewhere |
| 8 | Trajectory microscope | two unnormalized streams exist; belief-level metrics are not measurable here | M | **CONFIRMED · both sides** — writer contract in `shared/tool_state.py`, repo-side deriver, generator records the canonical schema hash in the manifest; non-computable metrics emitted as `not_measurable` |
| 9 | Intervention sequences | not implementable without breaking trusted-judge separation | L | **CONFIRMED · true runtime adaptation**, executed trusted-side (see *Reconciling item 9*) — policy baked at generation time, hash in manifest, no policy source in the agent container |
| 10 | Evaluator substitution | cheap if all evaluators read one judge run; exact if not (N× cost) | M | **CONFIRMED · views + costly opt-in** — `result["evaluators"]` derived from one judge run; `costly: true` gets a second run and is labeled; `D_eval` on the score vector, not binary pass/fail |
| 11 | Generator-vs-solver coevolution | only the model-free, gate-validated subset is honest today | L | **CONFIRMED · model-free loop** — mutations validated by existing gates, lineage recorded, reported as gate survival (never as difficulty) |
| 12 | Compiler → environment experiment spec | correct place for the typed interface; own the schema here | M | **CONFIRMED · generator owns the schema** — unknown intervention id / missing control / missing competing explanation = compile error |
| 13 | Provenance-bearing generator output | correct and cheap; pair key must be latent-spec hash, not case id | S | **CONFIRMED · record + enforce** — `generation.json` per member + `family_manifest.json`; grading recomputes ids and mismatch is `reward_denial` |
| 14 | Graph → research priors | out of repo scope; ship a validator that rejects control-free specs | S | **CONFIRMED · here, blocking** — with `--allow-advisory` for external authors |
| 15 | Epistemic-invariance family | falls out of 1–3; generic rename is the only risky op | M | **CONFIRMED · cross-cutting** — no new registry entry; `renameable_tokens:` allowlists, `twin_check` proves inertness |
| 16 | Measurement adversary | item 7 aimed at the metric; `specification_gaming` label already exists | M | **CONFIRMED · two tiers** — static exploits block CI, runtime exploits nightly |

---

## 1. Make every environment a causal intervention family

**Verdict.** Right direction, wrong amount of novelty. The pipeline is already
`latent task → instance → trajectory → judge`, and `axes` are already free-form substitution
overlays that can rewrite code (`glyph.architecture.hard` injects a whole `SpatialEncoderBlock`
class), filenames and class names (`css_state_machine.surface_deceptiveness`). What does not exist
is the object that *holds several coordinated generations of one base task*. `generate_env.py`
emits one directory and returns nothing; there is no family, no member list, no declared
expectation.

**Build.** Add a sibling of `axes:` — same shape, different semantics — plus a family expander.

```yaml
# envs/<env>/config.yaml  (purely additive; `axes` untouched)
interventions:
  terminology:
    equivalence: semantically_equivalent   # | observation_changing | evaluator_changing | task_changing
    expect: invariant                      # | sensitive | unspecified
    substitutions:
      "%%MODEL_CLASS%%": "GlyphTensorPipeline"
      "%%MODEL_FILE%%": "glyph_tensor_pipeline.py"
  visible_proxy:
    equivalence: observation_changing
    expect: sensitive
    substitutions:
      "%%VISIBLE_TEST_SRC%%": "visible_tests_adversarial.py"
    layout:                                # optional: swap which template fills a target path
      agent/workspace/visible_tests.py: "%%VISIBLE_TEST_SRC%%"
```

```python
# tools/family.py
def expand(base: Case, ids: Sequence[str], seeds: Sequence[int]) -> list[Member]: ...
# Member = base difficulty vector + one overlay + (equivalence, expect) + generation ids.
# generate_env.py gains: --interventions id[,id]  and  --manifest <path>
```

The equivalence classes are the payload: they are what lets a result say "the agent was wrong"
versus "the agent tracked the presentation instead of the invariant".

**Recorded.** Assumed *hybrid* (see Answers) — reversible until confirmed.

---

## 2. Explicit counterfactual twins

**Verdict.** The single genuinely high-value item, and better than the analysis assumes: for
`semantically_equivalent` twins the invariance claim is checkable **at generation time, with no
model involved** — the two directories must be identical after canonicalizing the declared renaming.
No LLM, no Docker, no torch.

**Build.**

```python
# tools/twin_check.py
def canonicalize(text: str, overlay: Overlay) -> str:
    """Map every renamed token back to its placeholder, strip overlay-only files."""

def check_twin(base_dir: Path, twin_dir: Path, overlay: Overlay) -> TwinReport:
    """semantically_equivalent  -> canonicalized trees must be byte-identical
       task_changing            -> they must differ (a no-op intervention is a config bug)
       evaluator_changing       -> agent-side trees identical, judge-side trees differ"""
```

Three failure classes it catches immediately, none of which anyone can currently detect: an
intervention that silently does nothing, an intervention declared invariant that in fact rewrites
the task, and an evaluator swap that leaks into the agent workspace.

**Open design point (asked).** What the pair is keyed on, and what "behavior(A) ≈ behavior(B)"
means concretely — score, answer string, or action distribution.

---

## 3. Turn the difficulty vector into a causal intervention vector

**Verdict.** Accept the distinction ("structurally deep" vs "made epistemically hostile"), reject
the parallel object where it duplicates an axis that already *is* an intervention: `glyph`
`visible_tests`, `moco` `naming`, `css_state_machine` `surface_deceptiveness`, `epistemic_games`
`framing` are presentation-layer interventions wearing difficulty clothing. Note the CLI is
positional (`parse_difficulty` requires exactly one level per axis, in order), so an intervention
vector must be **named**, and must not be merged into that string.

**Build.** `--interventions visible_proxy=adversarial,terminology=randomized`; a manifest field
`intervention_vector` kept separate from `difficulty_vector`; and a `class:` tag on existing axes:

```yaml
axes:
  - id: visible_tests
    class: presentation        # reclassified in place; still a difficulty axis, still positional
```

so `run_suite`'s case ids (`glyph__architecture=easy_..._seed-0`) gain a second segment for
interventions without renumbering anything that is already in `runs/` evidence.

---

## 4. First-class latent-variable layer

**Verdict.** Not missing — *singular*. `envs/epistemic_games/files/core.py` has exactly this: an
`Instance` dataclass carrying `hypotheses / prior / likelihoods / posterior / verdict /
actual_world`, serialized by `to_spec()` to JSON-safe form, baked into a judge-only
`instance_spec.py`, and re-derived by the judge from the seed — a mismatch is graded
`reward_denial`. The vocabulary proposed upstream (`task_state`, `causal_mechanism`,
`observable_state`, `proxy_signal`, `evaluator_state`, `agent_belief`) is a generalization of that,
and for 33 envs there is no such structure to generalize because the mechanism is fixed
hand-authored code.

**Build.** Promote the pattern into a required artifact: `latent_spec.json` at generation time,
never copied into the agent workspace; judge re-derivation stays per-env. `shared/latent_spec.py`
defines the key vocabulary and the `unavailable` sentinel.

**Honesty constraint worth keeping in the repo:** the derived spec records *which placeholders were
instantiated*, which for a template env is not a causal model. Marking that as `unavailable` is
what keeps `instance_oracle_gate.py`-style claims from silently inflating.

---

## 5. Generate misleading but internally consistent worlds

**Verdict.** Types 1 (false evidence) and 2 (incomplete evidence) exist as `symptom_mask` axis
levels in 4 envs — hand-authored prose plus one injected code branch, not generated. Type 3
(strategically selected evidence) exists **once**, in `epistemic_games`: `EVIDENCE_TABLE` specifies
`P(observation | policy)` and the mimicry invariant makes the strategic player's best inducer equal
the genuine player's own announcement. That is the only place in the repo where "the evidence was
produced by a policy that depends on the reader" is falsifiable, because the table is shipped to
the judge.

**Consequence.** An `information_policy` that is only prose in a prompt is unfalsifiable and does
not belong in a benchmark generator. The mechanism must be a deterministic module the judge can
re-run — the same contract the `renderer:` hook already enforces ("pure function of `subs`, seeded
randomness only").

---

## 6. "Same answer, different reasoning requirement"

**Verdict.** Already built — for one track. `shared/trajectory_semantics/generate_case.py`
generates matched cases (`relabel`, `syntax_noise`, horizon `T`, `query_type`), `certify.py`
certifies the system pair, and the three `envs/trajectory_semantics/*` envs expose
`parse_only / one_step / trajectory`. That is precisely "identical terminal answer, different
required computation". The gap is that this does not extend to patch-based envs, where "required
computation" is only observable as interaction depth from `environment-events.jsonl` and enforced
as a minimum set of touched files (already partially done: the judge "checks the patch touches the
files on the intended repair path", per README).

---

## 7. Shortcut-policy generation as a standard feature

**Verdict.** The repo already contains four: `examples/rope_hard_patch_{offset_only,pairing,
attention_cache,frequency}.patch` are hand-authored partial fixes against the real solution
`rope_hard_solution.patch`. And `tools/instance_oracle_gate.py` already runs reference validity per
case. So the cheap, falsifiable version of this item is not "generate policies", it is
**promote shortcuts to gated artifacts**: `envs/<env>/shortcuts/*.patch` + an expectation, and a CI
gate asserting each shortcut passes the visible/proxy check while failing the hidden invariant. A
shortcut that accidentally solves the task means the task has no invariant; that is currently
undetectable.

---

## 8. Trajectory microscope

**Verdict.** Two event streams exist and neither is canonical: env-side
`shared/tool_state.py:log_event` (`tool/action/status/summary` + arbitrary kwargs, per-env keys)
and harness-side `env_runner.py:_write_event` (`reset/step/submit` →
`episode_dir/environment-events.jsonl`, mirrored into `arena/artifacts.py` `ARTIFACT_NAMES`).
Normalizing them is a real win and cheap.

**Push back on the metric list.** Computable from the streams: action entropy, tool-selection
entropy, repeated-action rate, backtracking via path revisits, state revisitation,
time-to-first-diagnostic-run, irreversible-action timing, test-selection distribution. Not
computable without a belief model: `hypothesis-switches`, `information gained per action`,
`proxy exploitation` as a mental state. The repo already has the right instinct for this —
`arena/trajectory_runner.py` ends reports with `"These are behavioral intervention results, not a
serial-depth measurement."` The instrument should inherit that discipline, not quietly drop it.

---

## 9. Generate intervention sequences, not just interventions

**Verdict.** The one item that collides with the repo's security model. There is no per-step hook:
`env_runner.py` treats the workspace filesystem as the only state and the judge is terminal. An
agent-visible environment that adapts to the agent requires executable policy code inside the agent
container — which the README explicitly refuses ("Docker is the security boundary; the import
allowlist and event logs are integrity and observability layers"). A defensible version exists and
is weaker: record the full observation superset per episode, then *re-render* trajectories offline
under different information policies, giving adaptivity without runtime control in the agent loop.

---

## 10. Evaluator substitution as a generator primitive

**Verdict.** The only evaluator knob today is `scoring:` (`mode`, `pass_threshold`,
`partial_threshold`) — thresholds, not evaluators. But the expensive part of a judge run (apply
patch, validate, train, held-out generate, score) already produces a rich `result` dict with
`checks`, `metrics`, `notes`, `failure_mode`. Deriving several evaluator views from **that one
result** costs nothing: `E1 visible-only = result["checks"]["visible_tests"]`, `E4 outcome-only`,
`E3 trajectory-gated` computed from the event stream, all emitted side by side as
`result["evaluators"]`. An evaluator that needs its own training run cannot be cheap and should not
be pretended to be.

Formalizes `D_eval ≫ D_task` without any new compute in the common case.

---

## 11. Adversarial generator-vs-solver coevolution

**Verdict.** Every piece exists except the loop, and the loop's objective
`max_E [discriminative power − λ·ambiguity − μ·shortcutability]` is not computable here today: it
needs solver runs (provider budget) and a shortcut detector. `discriminative power` in particular is
undefined without a population of solvers. What *is* implementable model-free: generate a family,
apply mutations (rename / reorder / strengthen-mask / expose-shortcut), require every member to
survive `oracle_preflight` + `judge_preflight` + `instance_oracle_gate`, and record lineage with
`parent_generation_id`. Report gate survival, not difficulty.

---

## 12. Give the compiler a direct "environment specification" target

**Verdict.** This is the actual missing piece named by both analyses, and it is a schema, not a
coupling. `tools/suite_inventory.py` already produces exactly the shape needed (`manifest_type`,
`schema_version`, config sha256s, per-env axis census) and `tools/run_suite.py` consumes explicit
`cases:` from `experiments/*.yaml`. So an experiment spec is a superset of an existing case list.

```yaml
# spec/*.yaml  (compiled by tools/family.py --spec)
spec_version: 1
hypotheses:
  - id: H1
    statement: "agents maintain the global invariant"
  - id: H0
    statement: "agents exploit local proxies"
measurements: [invariant_score, proxy_score, intervention_sensitivity]
controls:
  - kind: evaluator_preserving_twin
expected_members:
  - {env: sheaf_schema_sync, difficulty: medium,medium, interventions: [terminology], expect: invariant}
claim_ceiling: behavioral_association_only
```

Compile-time failure on an unknown intervention id (listing the env's supported ids) is the property
that prevents this degrading into an ignored advisory.

---

## 13. Make generator output natively provenance-bearing

**Verdict.** Correct and nearly free. Today nothing records that a directory was generated from
what. Two design points matter more than the field list:

* `generation_id` should be a hash over `(env, config_sha256, difficulty_vector, intervention_vector,
  seed, generator_version)`; `judge_version` = hash of judge-side sources.
* The **pairing key** must be the *latent-spec hash* (task identity), not the case id — otherwise
  twins that legitimately differ only in prose look like different tasks, which is the exact thing
  the experiment is trying to separate. Fall back to base case id when no latent spec exists, and
  record that the fallback was used.

---

## 14. Use the research graph for priors, not tasks

**Verdict.** Correctly scoped out of this repo — and that is the right call, since the graph is not
in this checkout. The implementable residue is 30 lines: a validator that rejects a spec whose
hypothesis has no control member and no competing explanation. "Prevents idea soup" becomes a
mechanical check rather than a policy statement.

---

## 15. Epistemic-invariance family

**Verdict.** Given 1–3, the *declarations* come free: a family where every member is a transformation
with an equivalence class **is** the intervention layer. The genuinely new work is a generic
transformation library that mechanically applies to any env, and generic renaming is dangerous here:
judge code contains string checks and file names, so a blind regex over the generated tree can break
the oracle while looking like a clean rename.

Env-declared `renameable_tokens:` allowlists keep it safe, and the `twin_check` from item 2 is what
proves the rename was inert. `epistemic_games.framing` (narrative ↔ bare table) is already a shipped
example of a declared-invariant presentation transform.

---

## 16. Measurement adversary

**Verdict.** Item 7 rotated 90°, and the vocabulary is already there: `FAILURE_SPECIFICATION_GAMING`
and `FAILURE_OVERFIT_VISIBLE` exist in `shared/judge_lib.py`. Implementable without a model: a fixed
library of adversarial submissions (no-op patch, visible-tests-only patch, hardcoded metric,
stdout-spoof, judge-import tamper) run against a member, asserting each is caught by a named check;
an exploit is reported as "check X never fired" and the fix is a new check. This makes the measurement
protocol itself a thing that gets regression tests, which is the asymmetry the proposal correctly
identifies.

---

## Answers

All 27 recorded, in the order asked (5 rounds). Each entry states the chosen option and, where the
choice differs from my recommendation, the consequence that was accepted.

### Round 1 (part 1, items 1–6) — CONFIRMED

1. **Hybrid.** A global taxonomy file (`envs/interventions.yaml`) defines the *ids* and their
   equivalence semantics (`terminology`, `visible_proxy`, `monitoring`, `evaluator`, `retrieval_cue`,
   `tool_interface`); each env's `config.yaml` implements the subset it supports. An id used by a spec
   but not implemented by the env is a **compile-time error**, never a silent no-op — an inert twin
   otherwise reads as "the agent was invariant", which is the exact opposite of the measurement.
2. **Both halves.** `twin_check` at generation time (structural, model-free) plus score *and*
   normalized-answer delta at grading time. `pair_id = sha256(latent_spec)`, with an explicit
   recorded fallback to case id when no latent spec exists.
3. **Reclassify, don't duplicate.** `class: presentation | observation | evaluator | task` on existing
   axes; the new named vector is reserved for overlays that are not already axes.
4. **Require `latent_factors:` in all 34 configs.** *This overrides the recommendation*, which was to
   require it only for the procedural env and let the rest declare `unavailable`. Accepted consequence:
   ~33 configs of authoring before the layer is registry-complete. Two mitigations that keep the choice
   intact rather than half-abandoned:
   `tools/latent_factors_scaffold.py` emits a starter block per env from its constants + patchable
   files, and every declaration carries `declared_by: human|scaffold_unreviewed`, so a mechanical
   declaration can never be cited as a causal claim. Registry completeness is then a checklist, not a
   silent quality downgrade.
5. **Deterministic `information_policy` module** under the existing renderer-hook contract (pure,
   seeded, shipped to and re-run by the judge). Deception type 3 is only admissible where the policy is
   re-derivable; prose-level "the environment is adversarial" is not graded.
6. **Both, proxy first.** Interaction-depth proxy (judge-enforced repair path + measured depth from the
   event stream) on the 33 patch envs; one matched-answer family on the `trajectory_semantics` engine as
   a separate deliverable.

### Round 2 (part 1, items 7–12) — CONFIRMED

7. **Curated shortcuts, blocking gate.** Shortcut patches become first-class env content
   (`envs/<env>/shortcuts/*.patch` + `expected:` per evaluator). `tools/shortcut_gate.py` asserts each
   shortcut *passes* the visible/proxy check and *fails* the hidden invariant; a shortcut that passes
   the hidden invariant means the env has no invariant, and that fails the build. Blocking immediately
   for `epistemic_games` and `ts_*` (judges import without torch); under Docker in nightly for the 33
   `judge_lib.py` envs.
8. **Both sides, schema hash in the manifest.** This is cheaper than it looks: **33 of 34** configs
   inject `agent/tools/tool_state.py: shared/tool_state.py`, so defining the canonical vocabulary once
   in that shared module upgrades 33 envs with **zero config edits**. The outlier is `rope`, which ships
   its own `envs/rope/files/tool_state.py` (and 33 configs also inject `shared/judge_lib.py`), so item 8
   is: change one shared file, align rope's copy, add the deriver in `arena/`. `hypothesis-switches`,
   `information gained per action` and `proxy exploitation`-as-mental-state are emitted under
   `not_measurable` rather than dropped, matching `arena/trajectory_runner.py`'s existing
   `interpretation_warning` discipline.
9. **True runtime adaptation** — chosen over the safer offline re-render. Recorded constraint that
   makes it admissible rather than a boundary break: see *Reconciling item 9* below.
10. **Views + costly opt-in.** `evaluators:` in config; the judge derives
    `result["evaluators"] = {visible_only, hidden_full, outcome_only, trajectory_gated…}` from the
    single already-computed `checks/metrics` dict; anything that truly needs its own train/eval pass
    declares `costly: true`, runs a second pass, and is labeled so `D_eval` never mixes tiers
    silently. Distance computed over the **score vector** (binary pass/fail saturates and would hide
    exactly the metagaming signal).
11. **Model-free coevolution loop.** Mutations (rename, reorder, strengthen mask, expose shortcut) are
    validated by `oracle_preflight` + `judge_preflight` + `instance_oracle_gate` + the new
    `shortcut_gate`, with `parent_generation_id` lineage. Output is *gate survival* and
    *expectation violation*, explicitly not difficulty.
12. **Generator owns the spec schema**, compiler emits it. Compile-time error (not warning) on:
    unknown intervention id for an env, a hypothesis with no control member, a measurement with no
    member that produces it, and no competing explanation. `spec_version` + `generator_version` +
    config sha256s land in every manifest.

### Reconciling item 9 (runtime adaptation without giving the agent the environment's source)

Runtime mutation is compatible with the repo's security model **only if the mutating code never lives
in the agent container**. Adopted shape:

```text
env_runner.py (trusted, harness-side)
   step -> agent action -> policy.evaluate(state, history)  in the RUNNER process
        -> trusted write into /workspace (evidence removed, monitor regime changed, test set swapped)
        -> canonical event: {event: "environment_mutation", policy_hash, mutation_id, before, after}
   -> agent receives the resulting observation only
```

* The policy module is baked **at generation time** (like `renderer.py` today) and its sha256 goes in
  the manifest; the agent container gets no copy and no path to it.
* Every mutation is an *event*, not a silent filesystem change, so a run is re-derivable and an agent
  cannot be blamed (or credited) for an adaptation it could not observe.
* The agent-side `submit` diff is computed against the **post-mutation** pristine tree, otherwise
  adaptation reads as "the agent changed nothing".
* What this buys that the offline option cannot: the question the proposal actually asks — does the
  agent detect that the evidence process is adaptive, and does its probing policy change — becomes
  answerable, since `time_to_first_probe_after_mutation` is now a measurable event-stream quantity.
* Cost to accept: results depend on harness version, so `environment-family` claims are only valid for
  the recorded `runner_version`.

### Round 3 (part 1 items 13–16 + P2.1, P2.2) — CONFIRMED

13. **Record and enforce.** `generation.json` inside each member directory (so it travels with the
    tarred environment into the container) + `family_manifest.json` at the family root. Before grading,
    the runner recomputes `generation_id` from `(config sha256, difficulty_vector, intervention_vector,
    seed, generator_version)` and a mismatch is graded `reward_denial` — the precedent `epistemic_games`
    already sets with its baked `INSTANCE_SPEC` re-derivation. `judge_version` = hash of judge-side
    sources; the canonical event schema hash (item 8) and policy hash (item 9) are fields of the
    manifest, not side files.
14. **Validator ships here, blocking**, with `--allow-advisory` so a compiler-drafted spec can be
    expanded before it is epistemically complete. Consistent with 12: one authority, one failure mode.
15. **Cross-cutting, not a new family.** The transformation battery is items 1–3 applied to existing
    envs. `renameable_tokens:` allowlists per config — a blind regex over the generated tree can rewrite
    judge-side string checks and silently break the oracle while looking like a clean rename.
    `twin_check` is what proves the rename was inert.
16. **Two tiers.** Static exploits (no-op patch, judge-import tamper, hardcoded metric, stdout spoof)
    need no torch and block CI — which matters concretely here, since `shared/judge_lib.py` imports
    `torch` at module scope and cannot load in a plain test job. Runtime exploits (visible-test overfit,
    faked training failure) run nightly under Docker.
P2.1 **Two axes on `epistemic_games`: `publicity` (public|private|asymmetric) + `delivery`
    (delivered|uncertain|dropped), plus an acknowledgement bit.** Rejected alternative: modeling events
    as an intervention overlay — publicity changes what the agent is *entitled* to believe, so labeling it
    `semantically_equivalent` would be a false declaration. P2.9 (negative information) is folded in as
    `delivery: dropped`, not scheduled after it.
P2.2 **Explicit `K_A × K_D` cross-product with mutual estimates; `FACE_VALUE_BELIEF` generalizes to an
    observer-model table indexed by `K_D`; `verify_mimicry_invariant` stops raising and sets
    `observational_equivalent: bool`.** Mismatch cells become generatable, which is the point — v0 today
    has three level labels, one behavior, and a check that *forbids* strategic divergence.

### Interactions the answers created (both directions are good, one needs care)

* **Item 4 → item 13, load-bearing in a way neither analysis spotted.** `pair_id = sha256(latent_spec)`
  only separates *task-identity* from *presentation* for envs that have a latent spec. Requiring
  `latent_factors:` in all 34 configs is precisely what makes `pair_id` meaningful for the 33 template
  envs instead of falling back to case id — so the expensive option at item 4 removes the fallback at
  item 13. `evaluator_state` must be a declared factor in every config, or evaluator-shift twins collide.
* **Item 9 → item 13, conflict to resolve at build time.** Manifest verification and the `submit` diff
  both assume a static pristine tree; runtime mutation breaks that. Resolution: the manifest records
  `policy_hash` and the ordered `mutation_ids`; verification recomputes the *post-mutation* pristine
  state from the seed + policy, and the patch is diffed against that. Without this, every adapted episode
  fails provenance and reads as agent tampering.

### Round 4 (P2.3–P2.8) — CONFIRMED

P2.3 **Reason-about-hypergames**, not agent-as-player. The instance carries ground-truth `G` plus a
    per-side model (`G_A`, `G_B`) from a small cell library — missing action, wrong objective, wrong
    observability, wrong opponent identity — and the judge scores both the terminal verdict and whether
    the agent identified the asymmetry, since it knows `G`. Agent-as-player is recorded as a follow-on
    that requires the item-9 loop.
P2.4 **`sender_objective: informative|persuasive` + `partition: coarse|fine`.** Correct reading of the
    existing code: `EVIDENCE_TABLE` *already is* a signal policy `P(m|ω)`; what it lacks is a sender with
    an objective. Posteriors stay exactly computable, so no utility oracle is introduced.
P2.5 **Agent chooses which fragment to view next** (interactive). Chosen over the cheaper order-swap
    twin, so `epistemic_games` moves from single-shot `answer.py` to a multi-step episode. Two
    consequences recorded: (i) this is *cheaper than P2.3's player variant*, because `env_runner.py`
    already gives the agent `read_file` / `list_files` / `search` as actions — information selection is
    an existing capability, not a new action type; what must be added is fragment layout, and a judge
    that grades the path as well as the endpoint. (ii) It exposes the transport problem below, and
    cannot be graded honestly without resolving it.
P2.6 **Cross at the harness: `max_steps` scarcity × `visible_proxy` / `retrieval_cue` interventions**, with
    allocation measured from the event stream (first file opened, reads before first diagnostic run).
    `env_runner.py:700-724` already tracks the scarce resource, so no env-level "attention" variable is
    created and the compiler's own warning (text emphasis is not an attention experiment) cannot be
    triggered by accident.
P2.7 **Both tiers.** `epistemic_games` core gets N truthful fragments with a `coordination` parameter
    (exact while fragments are agent-independent); the 33 patch envs get *coordinated truthful artifacts*
    as an intervention — prompt, logs, visible tests and code comments independently supporting one
    misleading inference, generalizing what `moco.distractors` / `glyph.red_herring` already do.
P2.8 **`defect_class` as a second orthogonal field.** `equivalence` answers *what should stay the same*;
    `defect_class: A_false | B_missing | C_selective | D_provenance | E_multisource | F_drift` answers
    *what was done to the information*. `F_drift` carries `expect: unspecified` and is checked by a
    registry-wide audit, not per instance.

### The transport problem the answers exposed (items 8, 10, P2.5)

Checking the Docker flow, **the judge never sees the agent's trajectory today**:

* `shared/run_eval.sh` mounts only `-v ${SUBMISSION_VOL}:/submission:ro` into the judge — the patch, not
  the workspace; `logs/events.jsonl` lives on the agent's `--tmpfs /workspace` and dies with `--rm`.
* `/submission` **is writable by the agent** (`shared/submit.py` writes `agent.patch` there), so simply
  copying the log into the submission volume would hand the agent a forgeable trajectory.
* The harness path is the sound one: in controller mode the *host* builds the patch from the workspace
  (`submit.py`'s own message: *"Return the JSON action `{"type":"submit","confirm":true}`; the host
  creates the patch"*), and `arena/artifacts.py` already collects `environment-events.jsonl` — the agent
  has no write access to that copy.

So `trajectory_gated` (item 10), the microscope (item 8) and path grading (P2.5) are trustworthy **only
in the controller path**. There is no clean integrity mechanism for the interactive path: an HMAC would
need a key the agent can't read, but `/originals` is world-readable (`chmod -R a+rX /originals` in
`shared/Dockerfile.agent`) and the agent runs arbitrary code in the container.

### Round 5 (P2.9–P2.11 + transport) — CONFIRMED

* **Transport: controller path is authoritative.** Trajectory-derived evaluators and metrics exist only
  for host-collected logs; a `run_eval.sh` result reports `trajectory_gated: unavailable` — explicitly
  **not** `0.0` and not a failure, since a missing transport must never be scored as an agent's
  misbehaviour. No new mount, no signed-log fiction, no trust in agent-writable files.
* **P2.9: fold into P2.1 + require an inference over absence.** `delivery: dropped` supplies the
  non-arrival channel; the answer schema additionally requires the agent to state which hypotheses the
  silence rules out, so negative information is *graded* rather than merely present. An independent
  axis is unnecessary at v1, and the patch-env variant (absence as planted evidence) is held back
  because "the absence was deliberate" is unverifiable per instance without the item-5 policy module.
* **P2.10: `target: belief | response` in the core policy layer.** One field, three policy functions,
  exactly checkable — and it stays a crossed axis rather than a rung, which is what the compiler's
  anti-ladder rule requires. Rejected as inert: making it a registry-wide *intervention*, since the 33
  template envs have no opponent to shape and an intervention that can only be inert is the failure
  mode item 1's compile-time error exists to prevent.
* **P2.11: harness-level prompt assembly.** `eval_disclosure: none|exists|objective|protocol|generator`
  is applied where the episode prompt is built (`arena/`), not in env templates — one implementation for
  all 34 envs, latent task provably untouched, and it matches the fact that disclosure is a property of
  the *evaluation*. Recorded caveat: this measures **behavioral response to disclosed protocol
  information**, not "awareness" as an internal state; the same disclosure applied with a fixed latent
  task and a *different* judge (item 10) is what turns it into the `D_eval ≫ D_task` comparison the
  proposal actually wants.

## Part 2 — the 11 literature-grounded axes, checked against this repo

**Correction that governs the whole second analysis.** Its baseline is the compiler branch's proposal
documents, not this codebase. Grepping `envs/ shared/ tools/ arena/` for the constructs it says the
"current generator spec" is built from:

| Term the second analysis treats as existing | Files in this repo |
|---|---|
| `truthful_subset`, `same_fact_presentation` | **0** |
| `attention budget` | **0** |
| `next_test` (Family B's one-step target) | **0** |
| `hypergame`, `information design`, `negative information`, `delivery` | **0** |
| `level-k`, `common knowledge` | 1 each — both only in `envs/epistemic_games/files/core.py` |

So "your implementation spec currently has Attention Budget: flooding the environment…" and "the
present operator says essentially: choose truthful facts" describe a *specification document* on
`arena/01a107c8-epistemic-compiler`. Nothing here needs to be removed or migrated to satisfy those
items; every one of the 11 is additive, and **10 of the 11 have exactly one viable host in this
registry**: `epistemic_games`, the only env with a symbolic instance builder and a judge that
re-derives ground truth.

### The one place the code is weaker than either analysis assumed

`core.py` names three reasoning levels but implements two behaviors, and then stipulates the third:

```python
def level1_action(internal_state: str) -> str:
    # "level 1 reproduces level 0"
    return level0_action(internal_state)          # core.py:151-157

def verify_mimicry_invariant(l1, l3) -> None:      # core.py:178-189
    if l1 != l3: raise InstanceConstructionError(...)
```

`FACE_VALUE_BELIEF` (core.py:138) is the only observer model the engine can address: a fixed
action→belief map, with `denial` the unique strongest inducer of "missed". Consequences:

* **P2.2 (explicit `K_A` / `K_D` / mutual estimates) is not a new axis, it is un-hardcoding a
  constant.** The level ladder currently has 3 labels and 1 behavior, and the mimicry check *requires*
  the strategic player to be behaviorally identical to the honest one — so "deception depth" cannot
  vary at all today. Adding `K_D = 2` is not expressible: there is no level-2 observer model to induce
  against.
* **P2.1 (epistemic-event structure) is likewise a de-hardcoding.** The prompt literally prints
  `"Announcement policy (common knowledge):"` (core.py:467, 471, 483, 487) — publicity is fixed, one
  announcement, one observer, always delivered.
* **P2.9 (negative information) is absent by construction:** exactly one observation is drawn
  (`Instance.observation`), so there is no non-occurrence channel for an agent to reason from.
* **P2.6 (endogenous attention) has no host at all** — attention is not a variable in this repo, so
  "fixed vs endogenous attention" cannot be crossed with anything until item 4/8 of part 1 exist.

### Item-by-item

| # | Part-2 proposal | Host | Verdict |
|---|---|---|---|
| P2.1 | Epistemic events: public/private/asymmetric announcement, delivery uncertainty, acknowledgement | `epistemic_games` | **Best value/effort ratio of the 27 items.** Becomes 2 axes (`publicity`, `delivery`) + a `receiver_knows_sender_knows` bit; the posterior stays exactly computable, so the judge still re-derives truth. Rubinstein's EMG is then representable rather than described. |
| P2.2 | Level-k as a crossed axis (`K_A`, `K_D`, mutual estimates, mismatch cells) | `epistemic_games` | Accept, and note the finding above: today `K` is a narrative label over a single policy function. Requires a real observer-model table indexed by `K_D`, and the mimicry invariant must become a *reported regime* (`observationally_equivalent: bool`) rather than a construction error. |
| P2.3 | Hypergames: `G_A ≠ G_B` (missing player/action, wrong objective, wrong information structure) | `epistemic_games` | Genuinely additive and cheap there: the instance already carries per-world `Hypothesis{level, goal, behavior}`, so a `game_model` pair per agent is a data change, not an engine rewrite. Wrong-objective and wrong-observability cells are checkable; "which actions are available" changes the answer format and needs a judge-side expectation per cell. |
| P2.4 | Information design: vary the mapping `π(m\|ω)`, not just which true facts are shown | `epistemic_games` | Already half-present — `EVIDENCE_TABLE` *is* a signal policy `P(denial\|world)`. The real addition is a **sender-objective** parameter (informative vs persuasive) and a partition-refinement knob, both of which leave the Bayes computation exact. |
| P2.5 | D-BOS: multi-step belief trajectory `B₀→…→B_k`, endpoint/path divergence | needs part-1 item 8 first | Highest concept value, lowest current implementability. A k-step trajectory needs an interaction loop where the agent's *question* is an action; `epistemic_games` is single-shot `answer.py`. Realistic scope now: emit the *model's* predicted belief path for a fixed evidence order (order-swap twin = the matched control the proposal asks for) and score endpoint-vs-path separately. |
| P2.6 | Endogenous attention crossed with message design | none | Blocked: no attention variable exists (0 hits). Either part-1 item 4 creates an explicit `observation_selection` latent factor first, or this is a new sub-family, not an axis. |
| P2.7 | Multi-source "lying with truths" ecology (independent / coordinated / adversarial sources) | `epistemic_games`, then a new sub-family | Natural extension: replace one announcement with N fragments, each truthfully generated from a per-source policy, with a `coordination` parameter. Ground truth stays exact iff fragment semantics are independent of the agent; once sources react to the agent it becomes P2.5 and loses exactness. |
| P2.8 | A–F taxonomy: false / missing / selective / misleading-provenance / multi-source / drift | global | This is the right *naming scheme* for part-1 item 1's `equivalence` field. Recommend adopting it as the intervention taxonomy rather than inventing ad-hoc classes: A–D are observation-layer, E is ecology-layer, F is a property of the whole generator (and the one that can't be verified per-instance). |
| P2.9 | Negative information: non-occurrence as evidence | `epistemic_games` | Cheap and clean once P2.1 exists: `delivery: dropped` *is* negative information (an expected acknowledgement that did not arrive). Same code path, so schedule P2.9 as part of P2.1, not after it. |
| P2.10 | Reflexive control as a separate target axis (shaping the opponent's *expectation of my action*) | `epistemic_games` | Correct to keep orthogonal, and the code supports the split: today `level3_action` already targets a *belief state* (`target_state`), never an anticipated response. A third `target: belief \| response` bit is the minimal version. |
| P2.11 | Evaluation awareness as a protocol-awareness factor crossing every family | generator-wide, not env-local | The only part-2 item whose natural home is part 1's infrastructure: it is an `intervention` (`eval_disclosure: none\|exists\|objective\|protocol\|generator`) applied to the *prompt template* of any env, mechanically verifiable by `twin_check` (agent-visible prompt differs, latent task identical). This is also the single item the repo can already measure without new semantics: `epistemic_games` has 5 axes, so `5 axes × 5 disclosure levels` is a real experiment the day both exist. |

**Decisions (recorded in *Answers*, rounds 3–5):** P2.1 two axes, P2.9 folded into it · P2.2 explicit
`K_A × K_D`, mimicry invariant demoted to a reported regime · P2.3 reason-about, not play · P2.4 sender
objective + partition · P2.5 interactive fragment selection · P2.6 harness budget × message design ·
P2.7 both tiers · P2.8 orthogonal `defect_class` · P2.10 `target: belief|response` · P2.11 harness-level
`eval_disclosure`.

**Part 2's own three priorities, ranked against that table:** (1) epistemic-event operators — accept,
and fold P2.9 in; (2) hypergame × level-k — accept for `epistemic_games` only, and be aware it forces
the mimicry invariant to stop being a construction error; (3) multi-step information-environment
control — reject as *third*; it is the only one that needs infrastructure (item 8) that does not exist,
and its matched-control goal is delivered more cheaply by P2.1's order-swap twins.

---

Build order implied by the confirmed answers, split so that each stage is independently verifiable
**without `torch` or Docker** (which is what this sandbox and a plain CI job can actually run).

**PR-A — the typed interface (nothing model-facing).**
`#13` manifest + `generation_id` + `pair_id` (fallback recorded) → `#1` `envs/interventions.yaml`
taxonomy + per-env `interventions:` implementations + `tools/family.py::expand` with
unimplemented-id = compile error → `#2` `tools/twin_check.py` (canonicalized-tree equality; this is
what makes `#1` trustworthy rather than merely present) → `#3` `class:` on existing axes →
`#15` `renameable_tokens:` allowlist + the cross-cutting transform battery → `#12` + `#14`
`spec/environment_experiment` schema and its blocking validator (`--allow-advisory`).
Files: `generate_env.py` (`--interventions`, `--manifest`), `tools/family.py`, `tools/twin_check.py`,
`shared/experiment_spec.py`, `tests/test_interventions.py`, `tests/test_twin_check.py`.

**PR-B — measurement, and the transport rule that bounds it.**
`#10` `evaluators:` views derived from one judge run + `costly:` opt-in, with `trajectory_gated`
emitting `unavailable` on the `run_eval.sh` transport → `#7` `envs/*/shortcuts/*.patch` +
`tools/shortcut_gate.py` (blocking for `epistemic_games`/`ts_*`, nightly elsewhere) → `#16`
`tools/measurement_adversary.py` static tier blocking, runtime tier nightly → `#8` canonical event
vocabulary in `shared/tool_state.py` (33 envs upgraded at once) + `envs/rope/files/tool_state.py`
aligned + `arena/trajectory_metrics.py` deriver + schema hash recorded in the manifest.

**PR-C — the latent registry.**
`#4` `latent_factors:` in all 34 configs via `tools/latent_factors_scaffold.py`, every block stamped
`declared_by: human|scaffold_unreviewed`; this is what promotes `pair_id` from case-id fallback to real
task identity, and it requires `evaluator_state` to be a declared factor or evaluator-shift twins will
collide. Then `#5` the `information_policy` module under the renderer-hook contract, first used in
`epistemic_games`.

**PR-D — the epistemic engine (only here does `core.py` change).**
`P2.1` publicity + delivery axes → `P2.9` the required inference over absence → `P2.2` explicit
`K_A × K_D` + mutual estimates, with `verify_mimicry_invariant` demoted to
`observational_equivalent: bool` → `P2.3` `G_A/G_B` cells → `P2.4` sender objective + partition →
`P2.7` N fragments + coordination → `P2.10` `target: belief | response`.

**PR-E — interaction, last because three items gate on it.**
`#9` trusted-side runtime mutation (runner process, policy baked + hashed, `environment_mutation`
events, post-mutation pristine diff) → `P2.6` harness budget × interventions → `P2.11`
`eval_disclosure` in `arena/` prompt assembly → `P2.5` interactive fragment selection with path
grading (needs `#9` and the transport rule from PR-B) → `#6` matched-answer family on the
`trajectory_semantics` engine → `#11` model-free coevolution loop, which consumes all of the above and
reports gate survival only.

**Deliberately not built:** `P2.1`'s full-DEL variant; `#16`'s signed-log transport for the interactive
flow; `#11`'s solver-in-the-loop objective (`discriminative power` stays undefined until a solver
population exists); `P2.3`'s agent-as-player variant until `#9` is real; any env-level "attention
budget" variable.

---

## PR-A: what landed

Items 13, 1, 2, 3, 15, 12 and 14 — all model-free, torch-free and Docker-free.

| File | Role |
|---|---|
| `shared/generation_manifest.py` | `generation_id` / `pair_id` / tree and judge hashing / `verify_manifest`; item 13 |
| `envs/interventions.yaml` | the global id taxonomy with `equivalence`, `expect`, `defect_class`, `proof`; item 1 |
| `generate_env.py` | `--interventions`, `--parent-generation-id`, `--list-interventions`, overlay application, the rename pass, `generation.json`; items 1, 13, 15 |
| `tools/twin_check.py` | the three declaration rules, applied at generation time; item 2 |
| `tools/family.py` | baseline plus one member per intervention per seed, verification, `family_manifest.json`, `--spec`; items 1, 2, 12 |
| `shared/experiment_spec.py` | spec validation and compilation; items 12, 14 |
| `spec/invariant-vs-presentation.yaml` | a real spec that validates against the registry |
| `envs/{moco,glyph,css_state_machine,epistemic_games}/config.yaml` | first implementations: 9 intervention ids across 4 environments, `class:` on all 19 of their axes, `renameable_tokens` for glyph |
| `tests/test_causal_layer.py` | 19 tests, including a tamper test, an inert-overlay test, and one asserting these modules never import torch |

Four things only showed up while building it, and each changes how a later stage reads:

1. **"Nothing happened" had to be defined on normalized trees.** Two generated
   directories always differ — the instance label is baked into `run_eval.sh`, the
   Dockerfiles and the image names — so raw equality is meaningless and raw difference
   is never informative. The inert check is now "identical once the label is normalized
   away", which is the statement the declaration actually needs.
2. **Normalization is only sound for atomic values.** An overlay that replaces `MoCo`
   with `RetrievalPooledEncoder` can be mapped back and *proved* inert; one that
   replaces a rendered task text cannot, without rewriting whole files and possibly
   erasing the very difference being measured. So a differing value is normalized only
   when it is a single token; a *composed* value (e.g. `PATCHABLE_FILES`, which embeds
   the renamed file name) is accepted only when mapping its components reproduces the
   base value exactly; anything else reports `unverified`, never a pass. That is the
   mechanical form of the item-15 decision, and it makes the `epistemic_games`
   framing-style case behave correctly: prose-valued invariance is declared
   unfalsifiable instead of quietly true.
3. **`mechanism` had to be overridable per environment; `equivalence` and `expect` must
   not be.** moco renames through the substitution table, glyph — which has no naming
   placeholders at all — renames through the tree-wide pass; both are faithfully
   `terminology`. What an environment must never be allowed to relabel is the claim
   about what stays invariant. The rule caught a real bug in the first draft.
4. **Two generator bugs were in the way.** `mkdtemp` took the full output name as its
   prefix, so an absolute output path nested the temporary tree inside itself; and
   `%%ENV_NAME%%` was the whole path, which for a family member under an output
   directory produced image names like `/home/…/families/moco/moco__…_agent`. Both
   fixed: the label is the directory basename everywhere, and the manifest records that
   label rather than the incidental path.

**Deliberately not in PR-A.** Campaign integration: `tools/run_suite.py` and
`tools/suite_inventory.py` do not yet enumerate family members as cases, so a family
can be generated and verified but not *run* — that is the first item of PR-B. Also
absent: `class:` tags on the remaining 78 axes, and any evaluator-tier intervention —
`evaluator` and `reward_proxy` are declared in the taxonomy and implemented nowhere, so
requesting one is refused with the reason, which is the intended state until a second
valid oracle exists.

**Verified.** `pytest -q` = 99 passed, 1 failed, and the failure is the pre-existing
`test_a_chained_campaign_presents_a_resume_as_a_resume` from `e1b038a` documented under
*Census*, untouched by this branch. `tools/suite_inventory.py --matrix covering` still
reports 218 cases, `registry_clean: true`, `issue_count: 0`.
