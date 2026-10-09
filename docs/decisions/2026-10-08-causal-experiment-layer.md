# Generator upgrade: 27 proposals, reviewed against the code

Status: **all 27 recorded — 16 from part 1 (items 1–16) + 11 from part 2 (P2.1–P2.11), all
`CONFIRMED`.** Each answer is recorded verbatim in *Answers*; the resulting build order is in
*Build order*. **PR-A is implemented**, all five landed slices of PR-B (families runnable,
trajectory microscope, evaluator views, shortcut corpora, static measurement adversary) plus
the inventory's (intervention, view) expansion that closes PR-B's runnable remainder — and
**PR-C.1: the latent registry** (item 4): every config declares `latent_factors:`, every
instance carries `latent_spec.json`, and `pair_id` is structural registry-wide — and
**PR-C.2: the information_policy module** (item 5): evidence-selection declarations are
deterministic judge-shipped modules that the judge re-runs, with `epistemic_games` as the
first carrier and its `causal_mechanism` factor upgraded from `unavailable` to a declared
policy id. Remaining: the human review pass over the 33 scaffolded blocks, PR-D and PR-E.
Each record is at the end of this file.
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

**Recorded — CONFIRMED.** *Hybrid*: global ids in `envs/interventions.yaml`, per-environment implementation, and an unimplemented id is a compile error rather than a skip (Round 1, item 1). Shipped in PR-A.

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

---

## PR-B.1: families are runnable

The one gap PR-A left: a family could be generated and verified but not *run*. This
wires the intervention through the campaign lane and closes the loop from plan to
verdict, still without `torch`, a provider, or a container.

| File | Change |
|---|---|
| `env_runner.py` | `reset --interventions`; the runner **regenerates** the member rather than mutating a base tree; `generation_id` / `pair_id` / `provenance` recorded in state, in the reset event, and in the reset `info`; `_verify_provenance` runs inside `_submit` **before** the judge |
| `tools/instance_oracle_gate.py` | `validate_case` grades the intervened instance (it used to certify the base and let the episode run a twin); `verify_reset_matches_oracle` also compares intervention sets in both directions |
| `arena.py`, `arena/episode.py` | `--interventions` on the run parser, `EpisodeOptions.interventions`, threaded into `_reset_args`, the pre-provider oracle case, and the episode manifest |
| `tools/run_suite.py` | `_build_command` passes `--interventions`; each result row carries `interventions`, `family`, and the identity read back from the episode manifest; `reward_denial` is routed to `infrastructure_error` with an explicit message |
| `tools/suite_inventory.py` | `--family DIR` (repeatable): family cases instead of a matrix expansion, blocked on config drift / failed twin check, `--preflight` recomputes every member's `generation.json` |
| `tools/family.py` | member records now carry the runnable coordinates (`environment`, `config_path`, `seed`, `difficulty_levels`, `difficulty`, `interventions`) and `twin_check`; `expect` falls back to the taxonomy's declaration |
| `tools/family_report.py` | joins a suite manifest with a run checkpoint into per-pair verdicts, pooled by intervention id, with the claim ceiling attached |
| `tests/test_family_campaign.py` | 11 tests over all of the above |

**The bug this stage found, which PR-A's verification had hidden.** A
difference-proof declaration (`observation_changing`, `task_changing`) used to pass when
the two trees differed at all. But two generated directories *always* differ — the
instance label is in `run_eval.sh` — and a long member name exceeds the 128-character
limit that marks a value as normalizable, so an inert overlay at
`moco easy,easy,medium,medium,easy,easy` produced a **false pass**: the label was the
only difference and the check called that "the observation changed". Textual
invariance and textual difference both need the same anchor, so the criterion is now
"did a value this overlay actually sets move" — a substitution key it writes, a rename
with non-zero occurrences, or a layout override — computed from the recomputed
substitution tables rather than from file bytes. `semantically_equivalent` got the
dual rule: a renaming that fires nothing at this vector is refused as vacuous instead
of passing as an uninformative invariance.

Two consequences worth carrying forward:

1. **Provenance denial is not a scored zero.** `reward_denial` reaches the report as
   `infrastructure_error`, and the family report says `not_measurable`. A run whose
   bytes cannot be attributed to the plan that produced it has no model claim in it,
   and pooling it as `score = 0` would silently convert a harness defect into
   evidence that the agent failed.
2. **`pair_id` is now visible on the paid path.** Episode manifests and result rows
   carry it, so the same-task/two-artifacts structure that the whole design rests on is
   something a run report can check instead of something the generator asserted once
   at planning time.

**Still open in PR-B:** `#10` evaluator views (the taxonomy's `evaluator`/`reward_proxy`
ids remain unimplemented because a second valid oracle does not exist), `#7` shortcut
patches with a blocking `tools/shortcut_gate.py`, `#16`'s static measurement-adversary
tier, and `#8`'s canonical event vocabulary in `shared/tool_state.py`. The
`run_eval.sh` transport still cannot emit `trajectory_gated` results, so anything
depending on the trajectory microscope stays `not_measurable` by design until `#8`.

**Verified:** `tests/test_family_campaign.py` + `tests/test_causal_layer.py` = 30
passed; `tests/test_env_runner.py tests/test_scoring.py tests/test_paid_campaign_safety.py
tests/test_atria_campaign.py tests/test_exhaustive_campaign_recovery.py
tests/test_campaign_completion_contract.py tests/test_integration.py` = 30 passed;
`suite_inventory --matrix covering` unchanged at 218 cases with `issue_count: 0`.

---

## PR-B.2: the trajectory microscope (#8)

Both sides of one contract, so that "what did it look at and change on the way" becomes
a measurable property of a run instead of a claim about it.

| File | Change |
|---|---|
| `shared/tool_state.py` | canonical vocabulary: `KINDS`, `_KIND_RULES`, `classify_action()`, `event()`, `read_events()`, `EVENT_SCHEMA_VERSION`; `log_event` now stamps `kind` and `schema` |
| `arena/trajectory_metrics.py` | repo-side deriver: per-kind counts and first/last indices, four trajectory gates, host-vs-agent `claim_divergence`, `not_measurable` semantics, CLI |
| `env_runner.py` | host events carry `action_kind` + `schema`; reset is `lifecycle`; provenance block carries the schema digest |
| `shared/generation_manifest.py` | `event_schema_sha256` / `event_schema_version` recorded, and recomputed by `verify_manifest` |
| `generate_env.py` | hashes the shared module it copied from (absolute, not cwd-dependent) |
| `tools/family_report.py` | each pair now carries `trajectory` and `trajectory_shift` (count and first-index deltas, gate comparison); `--strict` unchanged |
| `tests/test_trajectory_events.py` | 29 tests (vocabulary, provenance, deriver, transport limit, forgeability) |

Four decisions worth recording because they were not forced by anything upstream:

1. **The vocabulary lives in `shared/tool_state.py`, not in a new module.** Every
   environment already copies that file into `agent/tools/`, so the contract reached all
   33 template environments with zero config edits. A second shared file would have meant
   a `layout:` change in 34 configs, which is how one convention becomes 34 slightly
   different ones.
2. **Classification is closed but lossy-by-refusal.** Unrecognized verbs keep their
   literal `action` string and count as `other`. `uncategorized` is reported, so a
   metric that quietly ignored an environment's own tool names is visible as a number
   rather than as a clean result.
3. **Two logs, two trust levels.** The episode's host log is written outside anything
   the agent controls; the workspace log is written by tools the agent can rewrite or
   skip. The deriver treats the second as a *claim* and reports the divergence —
   including that a shortfall usually means an unused tool, not a lie.
4. **Trajectory and score are separate verdicts.** `family_report` labels a pair
   `invariance_observed` from the score and *separately* reports `trajectory_shift`; a
   pair whose route changed while its score did not is not silently folded into
   "nothing happened", which is the failure mode an invariance claim is most exposed to.

**What PR-B's evaluator item will consume.** `#10`'s `trajectory_gated` view is these
gates evaluated on host-log metrics for the same episode — the substrate exists now, and
the transport rule from round 5 still applies: `run_eval.sh` reports
`trajectory_gated: unavailable`, and the controller path is authoritative. `not_measurable`
stays a first-class label so that choosing the container transport is visible in the
result rather than imputed as a zero.

**CI follow-up, recorded so it survives the sandbox.** The one failing test predates this
work (`tests/test_campaign_workflow_guard.py::test_a_chained_campaign_presents_a_resume_as_a_resume`,
broken by `e1b038a`). The fix, verified to turn all 6 guard tests green and then reverted
so this lane stays clean, is one line in the **"Run the covering campaign (fresh or
resumed)"** step's `env:` block of `.github/workflows/atria-campaign.yml` (after
`ARENA_ALLOW_COMPILE_ONLY`):

```yaml
GITHUB_EVENT_NAME: ${{ steps.mode.outputs.mode == 'resume' && 'schedule' || github.event_name }}
```

It belongs on the *campaign* step, not the chain step: the controller reads
`GITHUB_EVENT_NAME` when it decides whether to `rmtree` the restored state, and it is the
pinned code that does that — which is why the override has to live in the workflow.

---

## PR-B.3: evaluator views and `D_eval` (item 10, first half)

`shared/evaluator_views.py` derives every view from one judge result; `D_eval` is the
spread across the views that could actually be computed, with the excluded ones named.
`outcome_only` is the shipped rule, `integrity_gated` credits a structurally honest
submission, `behavioral_gated` withholds credit when any probe outside the
`judge_lib` infrastructure set failed, `trajectory_gated` adds the host-log gates, and
`adversarial` is the only view needing a second run.

The measurement-tier ids became real by being declared `mechanism: view`: `evaluator` →
`behavioral_gated`, `reward_proxy` → `integrity_gated`, implemented in moco. The choice
is the point of the item — an evaluator twin that also edited the judge would change what
"solved it" means, which is the one thing this comparison cannot survive. Consequences
that followed from taking that seriously:

1. `pair_id` does **not** move under a measurement change (identity is the task, not the
   ruler), and `twin_check` grew a fourth rule that requires the trees to be identical
   apart from the instance label *and* the recorded view to differ *and* `judge_tree`
   unchanged — with a note saying the proof is of the declaration, not of the score.
2. The view is applied at the single place a judge result becomes a reward
   (`env_runner._judge_result`), after the judge's own verdict has been validated, so an
   invalid judge result is an infrastructure error under any measurement. Verified
   behaviorally: identical output scores 1.0 under `outcome_only` and 0.0 under
   `behavioral_gated`, naming the probe that withheld it.
3. An uncomputable view is never a zero: `adversarial` without its second run is
   `not_run`, `trajectory_gated` on the shell transport is `unavailable`, both excluded
   from `D_eval` and listed as excluded.
4. `evaluators:` is validated, and the rules are the ones that keep the block honest:
   the authoritative view must be declared, cannot be `adversarial`, cannot also be
   opted into as costly, and a view overlay that selects the already-authoritative view
   is refused at resolution time — "the same episode twice".

**Not in this slice:** the second *episode* paths. `adversarial` still needs a runner
that re-grades the same artifact under perturbation, and `#7`'s shortcut patches are the
natural input to that re-grade, so they should land together; and `suite_inventory`
does not yet emit one case per (intervention, view) pair, so families vary the view only
through `tools/family.py`. Verified locally: causal + trajectory + family layers 71
passed; `env_runner`, `integration`, `scoring`, `paid_campaign_safety` 16 passed.

## PR-B.4: shortcut corpora and the gate that reads them (item 7, first tier)

`envs/<env>/shortcuts/index.yaml` + `*.patch` make "this measurement is gameable" a
checked artifact instead of a paragraph, and `tools/shortcut_gate.py` is the reader.
Two moco entries landed: `tau-rescaled-at-logits` (divides by τ outside the normalize —
bit-identical loss curve, lower reported loss, unchanged gradients; the visible test
asserts a ratio bound so it passes, the judge's `temperature_sensitive` probe rejects it)
and `queue-always-at-head` (writes newest-first with the offset still tracked, so
wrap-around stays correct and the recency property is gone).

**The rules the corpus taught, in order of how much they hurt.**

1. Patches must be cut against a *generated* instance, never against
   `envs/<env>/files/`. Those templates carry `%%PLACEHOLDER%%` text, so a hunk that
   looks fine against the template will not apply to an instance. The gate re-generates
   at each entry's declared vector and runs `patch --dry-run`, which converts that
   mistake from a silent skip into a CI failure — the failure mode I actually hit.
2. A patch cannot hold a verdict about a view that judges the *run*. `trajectory_gated`
   reads the agent's event stream; a corpus entry is applied by a script with no
   episode, so `measured_before_submit` is `not_measurable` → `unavailable`, which is not
   "rejected". Entries therefore say `run_dependent: {trajectory_gated: why}` instead of
   listing it, and the gate refuses the list form. `adversarial` is refused for the same
   reason in a different direction: it is a second *grade*, so it needs
   `perturbation.transform`, which is what `tools/evaluator_adversary.py` consumes.
3. `credits_under` must include the authoritative view. My first draft claimed moco's
   shortcuts were withheld by `outcome_only` too, which is not a shortcut but a failing
   attempt — no policy is ever rewarded for it, so it teaches nothing about the
   measurement. The definitional content of "shortcut" is *credited where the reward is
   computed*.
4. Strictness is a claim that needs a named witness: `strictness_evidence` lists the
   views the corpus is on the record about fooling, and each must appear in some entry's
   `withholds_credit_under` *with* the authoritative view credited. Demanding this for
   every declared view was wrong (my first version asked for a patch that `behavioral_gated`
   *credits*, i.e. a fix), so the obligation is per-corpus, not per-view.
5. `tools/evaluator_adversary.py` writes `judge.adversarial.json` — the file
   `evaluator_views` needs before `adversarial` stops reporting `not_run` — and knows
   exactly one perturbation: re-grade the *same* bytes on a fresh draw of the instance
   (`--seed-offset`, default 1; 0 is refused, since re-running the same measurement is not
   an adversary). Environment-specific transforms stay declared-but-uncertified rather
   than being approximated by generic code that would silently measure something else.

**Correction to the previous session's note.** The claim that moco's
`temperature_sensitive` check is gated on `RL_EVAL_TRAJECTORY_DIR` is wrong for this
repo: no such environment variable exists here, and `envs/moco/files/judge.py` marks the
check unconditionally from `eval_outputs.pt`. So `behavioral_gated` bites on every
transport that runs the judge, including the self-contained one — which is why the
entries withhold `behavioral_gated` outright rather than making it `run_dependent`.

**Still unverified, on purpose.** No `--judge` run happened in this checkout: torch is
absent, so the behavioral tier printed a reported skip and the corpus's verdict claims
(each `credits_under`/`withholds_credit_under` pair) remain *assertions the gate is
allowed to check but has not yet checked*. The static tier is green and blocking via
`tests/test_shortcut_gate.py` (`ci.yml` runs `pytest -q`, so no workflow edit was needed —
the same trick `#11` used for its guard). One pre-existing failure remains in the suite:
`test_campaign_workflow_guard.py::test_a_chained_campaign_presents_a_resume_as_a_resume`,
the one-line campaign fix the user asked to land as its own PR against `main`, not here.

**Not in this slice:** `suite_inventory` still does not emit one case per
(intervention, view); per-env adversary implementations beyond `seed_offset`; the `#16`
static measurement-adversary tier, which is next and can now reuse `PATCHABLE` and the
`index.yaml` reader instead of inventing its own.

## PR-B.5: the static measurement adversary (item 16, first tier)

`tools/measurement_adversary.py` is item 16 as answered: a fixed library of adversarial
submissions, each asserted to be caught by a *named* check, so "the guard never fired"
becomes "the guard does not exist here" and the fix is a check rather than a caveat. It
ships unpushed (the session that wrote it lost GitHub access mid-flight), so the work is
recorded here in full: files `tools/measurement_adversary.py`,
`tests/test_measurement_adversary.py` (8 tests, blocking), the `measurement_guards:` block in
`envs/moco/config.yaml`, and this section.

**Why the static tier is executable, not textual.** `shared/judge_lib.py` imports torch at
module scope, so a plain CI job cannot run a judge — but the two guards that decide these
exploits are *subprocess scripts* (`judge/patch_validator.py`, `judge/source_validator.py`)
that import only `ast`/`re`/`subprocess`, and `judge_lib.validate_submission` runs them as
scripts in that order. So the tier runs them with `JUDGE_PATCH_PATH`/`JUDGE_ORIGINALS_DIR`
pointed at a temp dir, and the thing it tests is the code that actually gates a reward. A
tier that re-implemented the allowlist would keep passing while the allowlist rotted.

**Exploits, and what caught them on the first run.**

| exploit | shape | caught by | what it proved |
| --- | --- | --- | --- |
| `no_op_patch` | one hunk whose `-` and `+` lines are byte-identical | `patch_valid` — "Patch has no effective change to file" | the `changed` flag in `modified_files_from_patch` is *not* the no-op guard; the byte comparison in `validate_patch` is |
| `test_rewrite` | edits `visible_tests.py` | `patch_valid` — "touches non-patchable file" | the corpus-level rule in `#7` and the harness rule agree, from opposite directions |
| `judge_import_tamper` | legal file, `import judge_lib` / `import os` | `sources_valid` | only reachable because `patch_valid` **passes** it — a reason to keep the two guards separate |
| `hardcoded_metric` | pre-baked numbers in a legal patch | *no allowlist*: audited on the guard instead | see below |
| `stdout_spoof` | forged/mismatched judge payloads | `env_runner._judge_result` corroboration | see below |

**Two findings that changed what this tier asserts.**

1. `hardcoded_metric` cannot be attacked through the guards at all, so the tier audits the
   guard's *provenance*: `guard_recomputes` walks `mark_check(result, "<name>", value)` and
   follows `value` through judge-side assignments, accepting only a trace that reaches a
   re-execution (`run`, `subprocess`, `torch.load`, …) and refusing one that reaches
   `result` / `metrics` — "derived from what the submitted code reported about itself".
   moco's three probes trace to `torch.load` in 3–5 hops and pass; a keyword-grep-style
   check fails. First version tokenized the expression with `.split()`, which produced
   garbage like `outputsgettau_ok`; it had to become an AST walk over `Name`/`Attribute`
   chains. Same trap as `#7`, again: the audit must read the **instance's** `judge/judge.py`,
   not `envs/<env>/files/judge.py`, whose `%%SCORING_PASS_THRESHOLD%%` text will not parse.
2. The `stdout_spoof` assertion I first wrote was wrong and the tool caught it. For the
   extractor, stdout is permissive by design: a valid verdict followed by log prose is
   accepted, and a corroborated verdict wrapped in a JSON list is accepted. That is not a
   hole — the authenticator is *corroboration* (exit status ⇔ verdict ⇔ score ⇔
   `failure_mode`), which an agent that can write the judge's stdout still cannot forge,
   because it does not control the judge's exit code. So the tier asserts both directions:
   eight self-contradictory payloads refused, and two legitimate shapes still accepted, so
   that a future "hardening" which starts rejecting real judge output is caught as the
   behaviour change it would be.

**Scope, honestly bounded.** `--grade` existed for a few minutes and was deleted: it graded
nothing, it only relabelled `instance_oracle_gate`'s variants, which would have made a fake
behavioral tier the blocking one. Runtime exploits are therefore *scheduled* —
`measurement_guards.runtime` must list `visible_test_overfit` and `faked_training_failure` or
the report says "a runtime exploit nobody scheduled is an exploit that is simply untested".
Envs with a judge but no `measurement_guards` block (`batchnorm_ema`, `epistemic_games`,
`glyph`, `rope`) are printed as "not yet attacked", advisory: blocking on a declaration that
does not exist yet would make this PR's CI red for four other envs' rollout work.

**Verified here:** `python tools/measurement_adversary.py` → `adversary: moco [ok] 7/7 exploits
caught by a named check`, exit 0, 0.7 s; `tests/test_measurement_adversary.py` 8 passed.

## PR-B.6: the inventory emits (intervention, view) cases

The last runnable item PR-B.3/B.4 left open: families varied the measurement tier
only through `tools/family.py`, so an evaluator experiment needed a generated
family directory before a scheduler could see it. `tools/suite_inventory.py
--interventions` now expands every matrix case with one planned case per
intervention the environment *declares* — the campaign lane regenerates each
instance from (environment, vector, seed, interventions) anyway, so a case only
needs the coordinates plus the declaration a report is read against. A
`view`-mechanism intervention carries the view it selects, which is the "view"
half of the (intervention, view) case: the measurement tier varies with no second
artifact and no second judge run.

What it deliberately does not do: no twin_check verdict per case. Nothing was
generated, so there are no bytes to verify; verification stays where it can
happen — at generation time in a family, at reset time via the provenance gate.
The flag is opt-in (the covering inventory stays at 218 cases), `--family`
refuses it rather than emitting a second unverified copy of verified members,
and `--preflight` generates the twin, not the baseline. Covering + flag: 335
cases, `ready_for_scheduler: true`, with `evaluator`/`reward_proxy` the only
view-carrying rows the registry can currently produce.

## PR-C.1: the latent registry (item 4, first tier)

`pair_id` stops being the case id. Every config now declares a `latent_factors:`
block, every generated directory carries a `latent_spec.json` derived from it,
and the manifest's `latent_spec_sha256` is the hash of the spec's *identity
projection* — so `pair_id` is literally `"P" + sha256(latent spec identity)[:16]`,
which is what Round 1 answer 2 said and what item 13 was waiting on. The
case-id-fallback branch of `pair_id()` is frozen, not deleted: pre-PR-C manifests
verify against it unchanged (the tracked `ev_base`/`ev_twin` evidence trees still
pass), and a config without a block is now a generation error, so no *new*
artifact can take the fallback.

| File | Role |
|---|---|
| `shared/latent_spec.py` | the factor vocabulary, block validation, derivation, the identity projection, presentation canonicalization, `parse_instance_spec` (read via `ast.literal_eval` — env code is never executed) |
| `tools/latent_factors_scaffold.py` | the mechanical mapping + `--write` / `--check`; emitted 33 of the 34 blocks, all stamped `declared_by: scaffold_unreviewed` |
| `generate_env.py` | validates the block, captures `(twin, base)` value pairs from `semantically_equivalent` overlays, writes the spec **before** the rename pass, records `latent_spec_declared_by` |
| `shared/generation_manifest.py` | the new `pair_id` form; `verify_manifest` recomputes the identity hash from the `latent_spec.json` in the tree — pair identity is only as real as the artifact it re-derives from |
| `envs/epistemic_games/config.yaml` | the one hand-authored projection (`declared_by: human`), see below |
| `tests/test_latent_registry.py` | 13 tests: registry completeness, scaffold-rule precedence, the four equivalence classes' pair relations, prose-twin merge, determinism, tamper, legacy fallback |

**The seven decisions that were not forced by anything upstream.**

1. **Identity is a projection, not the document.** Only `task_state`,
   `causal_mechanism` and `evaluator_state` enter the hash (plus environment and
   seed); `observable_state` and `proxy_signal` are recorded in full but never
   split a pair — an observation twin is the same task under different evidence,
   and a spec that hashed the whole document would turn every `retrieval_cue`
   into a different task.
2. **Cue-text patterns beat axis class tags.** moco's `QUEUE_HINT` lives under a
   `task`-class axis (queue_math); the scaffold maps `*HINT*`/`*COMMENT*`/
   `*CLUE*`/`*NOTE*`/`*DOCSTRING*`/`*HERRING*` names and `*TEST*` names to
   observable/proxy regardless of the tag, because the tag describes the axis's
   dominant character while the placeholder is the unit identity is built from.
   Without this rule the cue twin's pair splits and the family report loses its
   baseline comparison.
3. **The default is conservative: untagged placeholders go to `task_state`.** An
   over-broad identity splits pairs a later review merges; an over-narrow one
   silently merges tasks that are different, which is the worse error. This is
   also why `symptom_mask`-named axes in `cat_theo` (whose levels are real task
   knobs — `CHECK_DIM`, `TOLERANCE`) do not follow moco's observational
   `symptom_mask`: the id heuristic was dropped from the rule table.
4. **Presentation canonicalization runs on values, not files.** Identity values
   are mapped back through the `(twin, base)` pairs a `semantically_equivalent`
   overlay introduced — the same invertibility rule `twin_check` enforces on
   trees — so composed constants follow the renaming and map back exactly
   (`PATCHABLE_FILES` embeds `retrieval_pooled_encoder.py` in the twin and hashes
   to the base's digest). Rename-mechanism overlays need no pairs: they never
   touch the substitution table.
5. **The spec is written before the rename pass, and identity holds digests.** A
   glyph-style tree-wide renaming reaches the spec's raw factor values like any
   other text (the twin tree stays `GlyphCNN`-free, which the existing rename
   test asserts over *all* files), while the identity section carries only hex
   digests, which a word-boundary renaming provably cannot touch — so
   `verify_manifest`'s recomputation from the file survives the rename.
6. **`epistemic_games`' projection is hand-authored because a scaffold may not
   make it.** The baked `judge/instance_spec.py` carries the ground truth *and*
   its dress (`template`, `framing`, vocabulary text, `transcript`); hashing the
   file whole would keep narrative and bare-table framings apart — the exact
   split item 13 removes. `identity_keys` project the Bayesian core (priors,
   likelihoods, exact posterior, verdict fields, drawn observation,
   `hypotheses.level/behavior`), and the payoff is measured: framing *and*
   scenario twins now share a pair_id while `prior`/`evidence`/`presentation`
   overlays move it structurally — `twin_check`'s "task change not visible in the
   latent spec" failure is now a real proof for this env, not a declaration.
7. **`evaluator_state` records structure, not bytes.** A judge *content* hash
   would move under a declared renaming (the judge legitimately imports the
   renamed module) and split presentation twins; the collision `evaluator_state`
   exists to prevent is between different *measurements*, so it holds the scoring
   rule, the judge-side allowlists (canonicalized) and the judge file set.

**Honesty constraints kept:** `causal_mechanism` is `unavailable` with a reason
for all 33 template envs (the derived spec records which placeholders were
instantiated, which is not a causal model — item 4's own caveat, and the spec
document repeats it in `notes`), `agent_belief` is `unavailable` everywhere
(item 8 approximates it at run time), and `scaffold_unreviewed` blocks say so in
the document they produce.

**Not in this slice:** `#5`'s `information_policy` module; the human review pass
that moves blocks from `scaffold_unreviewed` to `human` (the checklist item 4
accepted); judge-side consumption — the judge's own re-derivation stays per-env
(`epistemic_games`' `INSTANCE_SPEC` equality check is untouched), and
`latent_spec.json` is generator-side identity, not a new judge input; and
`latent_factors` for the *axis-level* observation merges the scaffold's
conservative default creates in the 30 envs without interventions (a review
decision, not a mechanical one).

**Verified here:** `pytest -q` = 176 passed, 1 failed — the failure being the
pre-existing `test_campaign_workflow_guard` case documented under *Census*,
untouched by this branch. `tools/latent_factors_scaffold.py --check` = 34/34.
`tools/family.py` (terminology, retrieval_cue, evaluator over moco, seed 3) =
4 members, 3 pass, 0 fail. `measurement_adversary` 7/7, `shortcut_gate` 2/2,
covering inventory 218 cases `registry_clean` — all unchanged by the layer.

## PR-C.2: the information_policy module (item 5)

Prose in a prompt about how evidence was selected is not graded; a module the
judge re-runs is. An `information_policy` is the renderer-hook contract applied
to evidence selection: a deterministic file declared in the config, a pure
function of `(seed, subs)`, **shipped to the judge through the layout**, and
re-run there against the rebuilt instance spec. The type-3 deception claim
("this transcript was strategically chosen") is admissible in an environment
only where that claim is re-derivable this way — which is exactly the answer
recorded for item 5, and why `epistemic_games` is the first carrier.

| File | Role |
|---|---|
| `shared/information_policy.py` | the host contract: AST purity scan (stdlib allowlist + sibling env modules; no I/O, no dynamic code, no wall clock, no async; `select(context)` required), isolated loader mirroring `_run_renderer`, and the determinism probe (two runs, deep-copied contexts, disagreement refuses generation) |
| `generate_env.py` | config-level admission (a policy the layout does not ship under `judge/` is a config error, not a style note); runs the policy after the renderer — so it sees the baked instance spec — and before the fixpoint, so its placeholders resolve like any others; records `source_path` + `sha256` + selection |
| `shared/generation_manifest.py` | `information_policy: {source_path, sha256}` field; `verify_manifest` re-hashes the checkout source, so a policy edited after generation is caught like a drifted config |
| `shared/latent_spec.py` | top-level `information_policy` section (path, hash, selection) plus an honesty note; identity is untouched — a policy enters identity only where a factor declares its placeholder |
| `envs/epistemic_games/files/information_policy.py` | the first policy: `select()` parses the renderer's `JUDGE_INSTANCE` and returns `POLICY_ID` + `POLICY_RECORD`; `replay(spec)` is the judge-side entry recomputing the same record — one module, both sides of the boundary |
| `envs/epistemic_games/files/judge.py` | step 4b: `information_policy.replay(rebuilt) != POLICY_RECORD_BAKED` → `reward_denial`, the `INSTANCE_SPEC`-rebuild precedent; `information_policy_ok` joins the checks |
| `envs/epistemic_games/config.yaml` | `information_policy:` key, `judge/information_policy.py` layout entry, `causal_mechanism` upgraded from `unavailable` to `placeholders: [POLICY_ID]` |
| `tests/test_information_policy.py` | 19 tests: purity refusals, judge-shipment gate, stateful-policy probe refusal, generation records, determinism, manifest drift, and — because the epistemic judge is torch-free — three real judge subprocess runs: reference PASS with `information_policy_ok`, tampered baked record → `reward_denial`, tampered shipped module → `reward_denial` |

**The decisions that were not forced by anything upstream.**

1. **The record is recomputed, never echoed.** Every field of the epistemic
   record is re-derived from `core`'s declared machinery — the signal-table
   membership of the drawn behavior pair (exact `Fraction(str(float))`
   round-trip; every table value is short-decimal), the level-3 best response
   to a level-1 reader (the mimicry invariant, recomputed rather than read
   from the spec), and the verdict band from the exact likelihood ratio. A
   record that echoed the spec's prose would prove nothing.
2. **The comparison is literal dict equality, not string equality.** The
   record ships as a Python literal (`repr`) baked into `judge.py`; floats
   round-trip through `repr` without noise and dict equality ignores key
   order. (The first cut compared a `repr` *string* against an evaluated
   *dict* and denied everything — caught by running the real judge, which is
   the only test that counts here.)
3. **The shipped policy file is byte-identical to its checkout source.** The
   module contains no placeholder markers of its own, so staging's
   `%%...%%` resolution cannot touch it: what the judge ran is exactly what
   `verify_manifest` re-hashes, and an auditor can diff the two files.
4. **`POLICY_ID` enters identity; the record does not.** `causal_mechanism`
   now carries `[POLICY_ID]` instead of `unavailable` — a constant in v1, so
   every pair relation recorded under PR-C.1 (prose twins merge, prior
   overlay splits) is unchanged, and the tests re-prove it. The per-instance
   record lives top-level in the spec, outside the identity payload.
5. **Purity is scanned twice and probed once.** Config validation refuses
   early; `load_policy` re-validates the file on disk at generation time (the
   declaration is the file, not what passed validation earlier); and the
   determinism probe runs `select` twice on deep-copied contexts — a stateful
   policy that the AST scan cannot see (module-level counter) is refused by
   the probe, and the test does exactly that.

**Honesty constraints.** The v1 policy is a *constant* declaration: one public
announcement, always delivered, world 2 a level-3 speaker, the signal table
drawn from `core.EVIDENCE_TABLE`. It does not yet vary across instances and it
is not yet a causal account of delivery — it makes the selection process
re-derivable, which is the admissibility condition, and PR-D's
publicity/delivery axes (P2.1) are where the constants become parameters and
this module starts recording per-instance variation. The runtime trap is real
but narrow: it fires on tampering with the baked record or the shipped module
inside a generated tree; an agent cannot reach either (`judge/` is not
patchable), so its practical target is artifact provenance, not agent cheating.

**Not in this slice.** No second environment carries a policy (the other 33
configs have no evidence-selection story yet — declaring empty policies would
be registry theater); no delivery-axis variation (P2.1); no policy-versioning
scheme beyond the `_v1` suffix in the id.

**Verified here:** `pytest tests/test_information_policy.py` = 19 passed.
`tests/test_latent_registry.py + test_causal_layer.py + test_generator.py` =
40 passed (pair relations and pins unchanged). `tools/oracle_preflight.py` =
0 failures registry-wide (every generated judge still compiles, including the
new import). `tools/suite_inventory.py` = 34 cases, `registry_clean`,
`ready_for_scheduler`. `tools/latent_factors_scaffold.py --check` = 34/34.
`measurement_adversary --env epistemic_games` still reports the known
"no measurement_guards block" skip (one of the four envs listed under PR-B.5).
Full-suite numbers are in the commit message.
