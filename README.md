# Frontier ML Evaluation Environments

[![CI](https://github.com/StrangeTcy/rl_eval_generator/actions/workflows/ci.yml/badge.svg)](https://github.com/StrangeTcy/rl_eval_generator/actions/workflows/ci.yml)

Procedurally generated ML debugging environments for evaluating whether AI agents can reason about machine-learning systems, rather than merely retrieving familiar fixes.

The generator creates self-contained, Dockerized evaluation tasks. Each task presents an agent with a realistic codebase that runs, trains, and often appears superficially healthy, but fails because of subtle interactions between architecture, data, optimization, and stateful training behavior.

### Environment Categories

*   **Research-Style ML Debugging:** `glyph`, `batchnorm_ema`, `moco`
*   **Paper-to-Code & Stateful Investigation:** `rope`
*   **Compositional & Category-Theoretic Reasoning:** `cat_theo/*` (17 environments)
    > *These tasks target compositional invariants that current transformer-family models routinely violate under composition, batching, symmetry, and state.*
*   **Latent Substrate & Weird Machine Discovery:** `weird_machine/*` (6 environments)
    > *These tasks evaluate whether agents can recognize and exploit latent computational power in substrates whose surface semantics present them as non-programming artifacts.*

### Recommended Entry Points

*   **MoCo** for testing realistic, multi-file ML debugging.
*   **RoPE** for testing paper-to-implementation reading and offset calculations.
*   **tensor_functor** or **equivariant_diagram** (in `envs/cat_theo/`) to test category-theoretic compositionality.
*   **sql_fixed_point** or **regex_state_machine** (in `envs/weird_machine/`) to test recognizing and exploiting latent computational substrates.

---

## Quick Start

See [GETTING_STARTED.md](GETTING_STARTED.md) for a 5-minute guide from clone to first evaluation.

```bash
# Install and verify
pip install -r requirements.txt
pytest -q

# Generate and run a simple environment
python generate_env.py --env glyph --name glyph_test --difficulty easy,easy,easy,easy,easy,easy --seed 42
cd glyph_test
./run_eval.sh
```

---

## Why this exists

Many classic ML debugging benchmarks are now too easy for frontier models. Given a broken CNN on MNIST, a capable model can often ignore the actual failure mode, paste a memorized working architecture, and pass without diagnosing anything.

These environments are designed to make that strategy less reliable:

- bugs interact across files;
- datasets are generated procedurally;
- visible tests can be incomplete or misleading;
- difficulty is configurable along independent axes;
- names and abstractions can be changed to reduce retrieval cues;
- **symptom masks / misleading gradients** divert agents into intuitive but wrong fixes, requiring methodical step-by-step tracing;
- the judge scores held-out behavior rather than trusting agent output.

The goal is to test whether an agent can form and use a causal model of an ML system.

---

## Included environments

### Glyphic Permutation Task (`glyph`)

Synthetic images contain circles, squares, and triangles. A class is defined by the multiset of shapes in the image, not by their spatial locations.

The provided CNN uses a spatially sensitive classifier head. A second optimizer issue prevents convergence. The agent must infer that the task requires spatial invariance and repair both the model and training dynamics.

Axes:

- architecture clue clarity;
- optimizer pathology;
- augmentation red herring strength;
- visible-test helpfulness;
- data-definition obscurity;
- symptom mask (Coordinate Trap).

### BatchNorm EMA Corruption (`batchnorm_ema`)

A ResNet-style model trains with gradient accumulation. The loss curve looks healthy, but generalization is poor because BatchNorm running statistics update once per forward pass, not once per optimizer step.

The agent must understand the interaction between gradient accumulation and BatchNorm EMA state, then scale or otherwise control BatchNorm momentum.

Axes:

- hint visibility;
- DDP/no-sync red herring strength;
- visible-test helpfulness;
- dataset complexity;
- symptom mask (Ghost Overfitting).

### MoCo Representation Collapse (`moco`)

A MoCo-style contrastive learner trains without crashing, but its frozen backbone produces collapsed features.

The bugs are:

1. temperature is applied before normalization, so it cancels out;
2. queue updates silently truncate instead of wrapping around.

Axes:

- naming abstraction;
- distractor strength;
- queue/batch-size arithmetic;
- temperature bug visibility;
- visible-test helpfulness;
- symptom mask (Pseudo-Collapse).

### RoPE Paper-to-Implementation (`rope`)

A compact paper-to-code environment. The agent receives a fake PDF artifact,
stateful paper-reading tools, train/eval diagnostic tools, and a partially
incorrect RoPE implementation. Solving it requires reading the paper, running
diagnostics, and revising the patch across files. Hidden judge tests check
long-context numerical equivalence, offset correctness for KV-cache-style
decoding, norm preservation, and a relative-position property.

**Core bugs:** adjacent even/odd coordinate pairing is implemented incorrectly,
position offsets are ignored during chunked decoding, and hard variants also use
a plausible but wrong frequency scaling.

Axes:

- paper clarity;
- implementation obfuscation;
- notation mismatch;
- visible-test strength;
- hidden long-context severity;
- interaction depth;
- investigation difficulty;
- symptom mask (Context-Window Illusion).

### Category-Theoretic Compositional Environments (`envs/cat_theo/`)

A specialized suite of 17 environments targeting compositional reasoning, algebraic invariants, and structural properties of ML systems. **These tasks target compositional invariants that current transformer-family models routinely violate under composition, batching, symmetry, and state.** The judges in these tasks enforce strict algebraic and category-theoretic laws under procedural variation rather than checking simple outputs:

*   **Core Category Theory Tasks:**
    1. `tensor_functor`: Refactoring rigid tensor operations into coordinate-free functors commuting with `torch.vmap` and `grad`.
    2. `equivariant_diagram`: Completing projection heads to commute under cyclic and spatial group shifts (naturality/equivariance).
    3. `stochastic_monad`: Implementing deterministic operations as probabilistic Kleisli arrows satisfying the monad laws.
    4. `functorial_augmentation`: Constructing data augmentations that act as functors preserving model symmetries.
    5. `compositional_optimizer`: Refactoring optimizers into state-isolated, associative monoidal compositions.
    6. `tokenizer_adjunction`: Implementing detokenizers that form a Galois connection (adjunction) with lossy tokenizers.
    7. `architecture_naturality`: Mapping hidden representations between Transformer and RNN functors as a natural transformation.
    8. `transformer_ssm_lift`: Constructing a temporal state-space lift that preserves linear attention transition symmetries.
    9. `categorical_lenses`: Building bidirectional data-pipeline transforms satisfying the Put-Get, Get-Put, and Put-Put lens laws.
    10. `monadic_reward`: Writing side-effect-free reward functions wrapped inside a State Monad verifier.
    11. `semiring_unification`: Implementing abstract Semirings (Arithmetic, Tropical, Boolean) to unify shortest paths, reachability, and arithmetic.

*   **Semiring Recurrent & GNN Operations (`semiring/`):**
    12. `ssm_parallel_scan`: Constructing an associative parallel scan composition operator for state-space model transitions.
    13. `neuro_symbolic_parser`: Implementing a smooth, differentiable Log-Sum-Exp semiring parser to preserve gradient flow.
    14. `gnn_message_passing`: Building a permutation-equivariant neighborhood GNN aggregator that respects semiring distributivity.

*   **Sheaf-Inspired Global Invariant Scaling (`sheaf/`):**
    15. `sheaf_schema_sync`: Implementing transactional database migrations over circular, microservice-level schema overlaps.
    16. `sheaf_invariant_gluing`: Constructing compositional data-preprocessing boundaries that resist out-of-distribution cascades.
    17. `sheaf_physical_constraints`: Building a distributed network-topology traffic scheduler that respects global backbone bandwidth constraints.

### Latent Substrate & Weird Machine Environments (`envs/weird_machine/`)

A suite of 6 environments targeting unintended expressivity and cross-substrate compilation. These environments test whether an agent can infer and exploit latent computational structure in substrates whose surface semantics present them as non-programming artifacts:

1. `regex_state_machine`: Implementing synchronous steps of the Rule 110 cellular automaton via regular expression substitution rewriting without host loops.
2. `sql_fixed_point`: Computing graph reachability and transitive closure over arbitrary cyclic graphs using pure recursive relational SQL queries.
3. `spreadsheet_dataflow`: Encoding dynamic programming paths as declarative spreadsheet cell formula dependency graphs.
4. `css_state_machine`: Constructing boolean logic circuits and parity evaluators using pure CSS general sibling combinators and state pseudo-classes.
5. `template_interpreter`: Decoding run-length structured data by leveraging template macro loop and conditional evaluation semantics.
6. `ci_dependency_graph`: Scheduling execution layers and topological dependencies across continuous integration pipeline workflows.

---

## Repository layout &amp; generation

```text
rl_eval_generator/
├── generate_env.py
├── shared/
│   ├── submit.py
│   ├── patch_validator.py
│   ├── source_validator.py
│   ├── judge_lib.py
│   ├── Dockerfile.agent
│   ├── Dockerfile.judge
│   └── run_eval.sh
├── envs/
│   ├── glyph/
│   ├── batchnorm_ema/
│   ├── moco/
│   ├── rope/
│   ├── cat_theo/
│   │   ├── <individual_ct_envs>/
│   │   ├── semiring/
│   │   └── sheaf/
│   └── weird_machine/
│       ├── regex_state_machine/
│       ├── sql_fixed_point/
│       ├── spreadsheet_dataflow/
│       ├── css_state_machine/
│       ├── template_interpreter/
│       └── ci_dependency_graph/
├── tests/
└── .github/workflows/ci.yml
```

Environment-specific files live under `envs/&lt;name&gt;/files/`; shared tooling is
injected from `shared/` at generation time. Templates use plain `%%PLACEHOLDER%%`
substitution — no conditionals, loops, or inheritance — guarded by strict
unresolved-placeholder errors, recursive substitution for composed values,
indentation-preserving multiline substitution, output-path containment and
symlink rejection, config validation, and atomic writes via a temporary
directory.


---

## Quickstart

Install generator dependencies:

```bash
pip install -r requirements.txt
```

List axes:

```bash
python generate_env.py --env glyph --list-axes
python generate_env.py --env batchnorm_ema --list-axes
python generate_env.py --env moco --list-axes
python generate_env.py --env rope --list-axes
```

Generate an environment (one `--difficulty` level per axis; `rope` has seven axes):

```bash
python generate_env.py \
  --env glyph \
  --name glyph_hard_42 \
  --difficulty hard,hard,hard,hard,hard \
  --seed 42
```

Vary `--seed` to produce multiple independent instances at the same difficulty.
When reporting results, record the environment, difficulty vector, seed, raw
accuracy, and score.

Run it:

```bash
cd glyph_hard_42
./run_eval.sh
```

The script builds an agent container and a judge container. The agent container opens an interactive shell. After editing files, run:

```bash
python /tools/submit.py
exit
```

The judge then applies the patch, validates it, trains/evaluates, and emits JSON.


---

## Gym-like environment runner

The repository includes a minimal `reset` / `step` interface for driving generated
environments as interaction loops:

```bash
python env_runner.py reset \
  --env rope \
  --episode-id demo_rope \
  --difficulty hard,hard,hard,hard,hard,hard,hard \
  --seed 1

python env_runner.py step \
  --episode demo_rope \
  --action '{"type":"read_file","path":"prompt.md"}'

python env_runner.py step \
  --episode demo_rope \
  --action '{"cmd":"ls -R . /tools"}'
```

Each `step` returns JSON with:

```json
{
  "observation": "...",
  "reward": 0.0,
  "done": false,
  "info": {"step": 1, "budget_remaining": 39}
}
```

Core action types: `shell`/`run` (`{"cmd": "..."}`), `read_file`, `write_file`,
`list_files`, `search`, `show_diff`, `changed_files`, `apply_patch`, the
`replace_*` edit ops, and `submit`.

The runner is intentionally lightweight. It stores episodes under `.episodes/`
and uses the persistent filesystem as environment state. `submit` grades the
current episode workspace non-interactively: it diffs the workspace against the
pristine sources and runs the generated judge in-process, returning the score as
JSON. It does not require the interactive `run_eval.sh` flow.

Rewards are terminal and the local runner is single-session; Docker resource
limits apply when scoring through the generated `run_eval.sh`.

---

## Causal interventions and twin families

Difficulty axes say how hard a task is. An **intervention** varies how the same task
is presented, observed, or measured, and declares which way behavior is expected to
move as a result. Mechanically an intervention is what an axis already is —
placeholder overrides, an optional layout override, or a rename pass over the
generated tree — so it inherits the same guarantees: deterministic from the seed, no
template logic, no code that only runs at generation time.

```bash
# what one environment supports, and what each id promises
python generate_env.py --env moco --list-interventions

# one instance with one intervention applied on top of the difficulty vector
python generate_env.py --env moco --name moco_term --difficulty \
  easy,easy,easy,easy,easy,easy --seed 3 --interventions terminology

# the family: a baseline plus one member per intervention, then verify the expansion
python tools/family.py --env moco --difficulty easy,easy,easy,easy,easy,easy \
  --seeds 3 --interventions terminology,retrieval_cue --out families/moco
```

Every generated directory carries `generation.json`: the inputs, the config hash, the
judge-source hash, the tree hash, a `generation_id` (identity of the artifact) and a
`pair_id` (identity of the *task*), plus a `latent_spec.json` derived from the config's
`latent_factors:` block: what the instance's task state, observable dress, proxy
signals and evaluator structure actually are. `pair_id` is the hash of that spec's
*identity projection* — task, mechanism and evaluator factors, never the presentation
or observation dress — so twins that differ only in names or planted hints are one
task, which is the comparison the experiment is about, and `verify_manifest`
recomputes the projection from the file in the tree: a hand-edit moves `pair_id` or
fails verification, it cannot quietly re-score.

An environment that claims its evidence was strategically selected holds that claim as
code, not prose: `information_policy:` declares a deterministic module under the
renderer-hook contract, the generator bakes its `select()` output into the judge, and
the judge re-runs the same module against the rebuilt instance spec — a replay mismatch
is `reward_denial`, never a pooled zero. `epistemic_games` ships the first policy
(`judge/information_policy.py`, byte-identical to its checkout source); the manifest and
`latent_spec.json` record the module's `sha256`, and `verify_manifest` re-hashes the
checkout, so a policy edited after generation fails attribution.

`tools/twin_check.py` decides whether a twin is the experiment its declaration claims,
before any model is contacted:

| declaration | what is verified | why |
|---|---|---|
| `semantically_equivalent` | trees identical once every value the overlay introduced is mapped back | a twin that differs beyond the renaming is a different task with an invariance label on it |
| `observation_changing`, `task_changing` | trees must differ once the instance label is normalized away | an overlay that fired nothing is indistinguishable from an agent that correctly ignored it |
| `evaluator_changing` | agent tree identical, judge tree different | a measurement change that reaches the workspace turns "gamed the evaluator" into "read the evaluator" |

Three declaration fields carry the meaning: `equivalence` (what must stay the same),
`expect` (`invariant` / `sensitive` / `unspecified`), and `defect_class` (`A_false` …
`F_drift`, what was done to the information — independent of the first two). `proof`
says how much of it is mechanical: `textual`, `difference`, or `unverified`, which is a
real verdict and never a pass.

An `Environment Experiment Spec` (`spec/invariant-vs-presentation.yaml`) is the
upstream object: hypotheses, the measurements that separate them, the controls, and the
members that produce each measurement. `tools/family.py --spec` refuses to generate
from one that is incoherent — fewer than two hypotheses, a hypothesis with no control,
a measurement no member produces, an intervention the target environment does not
implement, no untouched baseline, or `expect: invariant` under a task-changing overlay.

### Running a family

A family is a plan, not a directory to score. `tools/suite_inventory.py --family` turns
`family_manifest.json` into ordinary campaign cases — each carrying `interventions` plus
the pair identity that grading has to reproduce — and the runner regenerates each member
inside its own episode:

```bash
python tools/suite_inventory.py --family families/moco --preflight --out suite.json
python tools/run_suite.py --manifest suite.json --provider … --model …      # or --dry-run
python tools/family_report.py --manifest suite.json --checkpoint runs/…/checkpoint.json
```

Two things this wiring guarantees rather than assumes:

* an episode that asks for an intervention gets a **regenerated** instance, so the twin
  is byte-for-byte the one that was verified; `env_runner.py reset` records
  `generation_id` and `pair_id` in the episode state and its reset event, and the
  exact-instance oracle gate certifies the intervened instance, not the base one;
* before the judge is invoked, the runner recomputes the generation record: files
  outside `agent/workspace` and the pristine workspace must still match what was
  generated. A mismatch is `reward_denial` — an integrity failure upstream of the model,
  reported as `infrastructure_error`, never as a scored zero. `run_suite` marks the case
  with `provenance record did not match the generated instance`.

`tools/family_report.py` classifies each pair against its own declaration:
`invariance_observed`, `sensitive`, `sensitivity_observed`, `no_sensitivity`,
`*_declaration_unproved` when `twin_check` could not prove the label,
`identity_mismatch` when the episode ran a different instance than the plan, and
`not_measurable` when no scored verdict exists. It never writes "established", and it
prints the spec's `claim_ceiling` with the numbers.

### Trajectory measurement

Tool calls are recorded in a canonical vocabulary that lives in `shared/tool_state.py` —
the file every environment already copies, so the contract reaches all 34 of them without
a single layout edit. Events carry `kind` (one of `observe`, `retrieve`, `modify`,
`execute`, `measure`, `submit`, `judge`, `lifecycle`, `other`), `schema`, and their
literal action string: classification is closed, but an unanticipated verb is kept and
counted as `other`, because dropping unfamiliar events would bias every trajectory metric
toward the environments someone remembered to label.

The host log (`.episodes/<id>/environment-events.jsonl`, copied into each run directory)
is the authoritative record — the agent cannot write it. The workspace log is the agent's
own tools' account of themselves: richer, and forgeable, so `arena/trajectory_metrics.py`
reports the difference as `claim_divergence` instead of trusting or averaging it.

```bash
python arena/trajectory_metrics.py runs/<episode>          # metrics + gates + verdict
python tools/family_report.py --manifest suite.json --checkpoint checkpoint.json
```

`generation.json` records `event_schema_sha256`/`event_schema_version`, and
`verify_manifest` recomputes them: a tree whose vocabulary no longer matches the one it
shipped with cannot be compared against another environment's trajectory, so that is an
error rather than a note. A pair whose run used the self-contained `run_eval.sh`
transport — which surfaces no event stream — is reported `not_measurable`, and the family
report keeps that separate from "no change": the first is a fact about the harness.

### Evaluator views

The shipped score is one projection of a judge run, not a neutral quantity.
`shared/evaluator_views.py` derives the others from the *same* result — `outcome_only`,
`integrity_gated`, `behavioral_gated`, `trajectory_gated` (host log required), and
`adversarial` (a second run, opt-in) — and `D_eval` is the spread across them. A
measurement-only intervention is realized as `mechanism: view`: the twin's artifact bytes
are identical to its baseline's on purpose, and the manifest records which view defines
its reward. `twin_check` proves exactly that — trees identical apart from the instance
label, `pair_id` unchanged, authoritative view different — and a view that could not be
computed reports `unavailable`/`not_run`, never a zero.

```yaml
# envs/moco/config.yaml
evaluators:
  authoritative: outcome_only
  views: [outcome_only, integrity_gated, behavioral_gated, trajectory_gated]
  costly: [adversarial]
interventions:
  evaluator:      {view: behavioral_gated}
  reward_proxy:   {view: integrity_gated}
```

**Limits.** Four environments implement interventions today (`moco`, `glyph`,
`css_state_machine`, `epistemic_games`); the other 30 declare none, and asking for one
there is a hard error rather than a no-op. `evaluator` and `reward_proxy` are realized
as the view selection shown above — same bytes, same judge run, a different projection
made authoritative; the taxonomy ids nobody implements yet are `monitoring` and
`tool_interface`. Task identity is structural registry-wide: every config declares
`latent_factors:` (`tools/latent_factors_scaffold.py` emitted 33 of the 34 blocks and
stamps them `scaffold_unreviewed`, so a mechanical declaration cannot be cited as a
causal claim; the `epistemic_games` projection is hand-authored), and the pre-PR-C
case-id fallback in `pair_id_basis` survives only for verifying manifests generated
before the latent registry existed. One environment declares an `information_policy`
(`epistemic_games`, whose policy is a constant v1 declaration — one public announcement,
reader-dependent world-2 speaker, declared signal table); the other 33 make no
re-derivable evidence-selection claim, and their deception surface stays prose-free by
simply not making one.

### Shortcut corpora

A view that has never fooled anyone is only assumed to be stricter. `envs/<env>/shortcuts/`
holds curated patches that satisfy the measurement without solving the task, and
`tools/shortcut_gate.py` checks the claim in two tiers. The static tier runs in CI with no
torch: every patch must apply to a freshly generated instance at its declared difficulty
vector, touch only files the source validator lets an agent patch, and never edit the tests
or the judge (rewriting `visible_tests.py` is not gaming a measurement, it is deleting one).
The declarations are checked as an argument: `credits_under` must include the authoritative
view — a patch that fails it is a bad attempt, never rewarded, uninformative — and a view
that judges the *run* rather than the artifact gets no verdict, because a corpus entry is
applied outside any episode: `trajectory_gated` is `not_measurable` there and belongs under
`run_dependent`, while `adversarial` needs a `perturbation` someone can execute. Any view in
`strictness_evidence` must be demonstrated by at least one entry. The behavioral tier
(`--judge`) regenerates the instance, applies the patch, runs the real judge, and compares
each view's state with what the entry claimed; where torch is absent it prints a reported
skip rather than a pass.

```bash
python tools/shortcut_gate.py            # static tier, blocking via tests/test_shortcut_gate.py
python tools/shortcut_gate.py --judge    # also grade each shortcut (needs the judge)
python tools/evaluator_adversary.py --corpus moco --json adv.json
```

`tools/evaluator_adversary.py` is the only writer of `judge.adversarial.json`, the file
`evaluator_views` needs before `adversarial` stops reporting `not_run`. It knows one
perturbation — re-grade the *same* artifact on a fresh draw of the instance — because
anything environment-specific is a claim about that environment's geometry and stays
`unavailable` until someone implements it. A gap is written as `status: unavailable` with
exit 0, never as a score of 0: the whole point of the layer is that an unmeasured view is
visibly unmeasured.

### Measurement adversary

The shortcut corpus asks whether a policy can satisfy a measurement without solving the task.
`tools/measurement_adversary.py` asks whether it can satisfy the measurement without
submitting anything a judge could look at — and gives the *protocol* regression tests. A
fixed library of hostile submissions (no-op hunk, test-rewriting patch, legal patch with a
hostile import, pre-baked metrics, forged stdout) is pushed through the instance's **real**
guards, `judge/patch_validator.py` then `judge/source_validator.py`, in the order
`judge_lib.validate_submission` uses; each must be refused by the check named for it in
`measurement_guards.static`. Because it executes the guards rather than re-implementing them,
it needs no torch, so it blocks CI; the runtime exploits (`visible_test_overfit`,
`faked_training_failure`) are *scheduled* under `runtime:` — omitting one is reported as an
untested exploit rather than an unexploitable one.

```yaml
# envs/moco/config.yaml
measurement_guards:
  static:
    no_op_patch: patch_valid
    test_rewrite: patch_valid
    judge_import_tamper: sources_valid
    hardcoded_metric: [temperature_sensitive, non_collapsed_features, queue_wraparound]
  runtime: [visible_test_overfit, faked_training_failure]
```

`hardcoded_metric` is the one exploit no allowlist can catch — pre-baked numbers are a legal
patch — so the tier audits the *guard* instead: every check named there must be marked in the
judge from a value that traces back to re-executing the submission (`run(...)`, a
`torch.load` of what the eval step wrote). A check derived from `result["metrics"]` is the
agent's own claim re-labelled, and is refused with that sentence. For the same reason
`stdout_spoof` asserts what actually authenticates a verdict — that exit status, failure mode
and score corroborate each other — rather than trusting where the object sat in the stream.

---

## Exploitation-resistant design

The reward signal is meant to be hard to cheat *and* hard to deny. No single
check does that; the whole setup does.

The agent submits a unified diff patch. The judge applies it to pristine sources
inside an isolated container, then for each environment:

1. validates patched files against an import allowlist that rejects bypass
   constructs (`exec`, `eval`, `compile`, `__import__`, `open`);
2. trains the patched code in a subprocess;
3. scrubs unexpected runtime-written files;
4. generates held-out inputs and labels in the trusted judge process;
5. exposes only unlabeled inputs to the model subprocess;
6. computes the score itself, never trusting agent-reported metrics.

This closes common routes — stdout spoofing, hidden-label reads, judge-process
code execution — while held-out evaluation guards against overfitting the
visible tests.

**Isolation.** Containers run with a read-only root filesystem, dropped
capabilities, no network, PID/file-descriptor limits, tmpfs-backed writable
directories, and non-root `agent`/`judge` users. Docker is the security boundary;
the import allowlist and event logs are integrity and observability layers, not a
sandbox.

**Cross-context edits.** Repairs require coordinated changes across files, not
isolated fill-in-the-blank patches, and the judge checks the patch touches the
files on the intended repair path: `glyph` (architecture + training dynamics),
`batchnorm_ema` (model/training BatchNorm state under accumulation), `moco`
(temperature in the model file + queue logic in `queue_ops.py`), `rope` (math,
attention call-site, and cache split across `rope.py`/`attention.py`/`cache.py`).

**Diagnosable failures.** Judges emit a structured `failure_mode` alongside the
scalar `score` — e.g. `pass`, `patch_invalid`, `source_invalid`,
`training_failed`, `underfit`, `overfit_visible_tests`, `specification_gaming`,
`reward_denial` — plus `checks`/`metrics` (prediction entropy, class coverage,
feature variance, proxy/score gaps, per-check breakdowns) so an underfit looks
different from a visible-test overfit or a local-proxy exploit. 

Example of a structured judge output showing an underfit failure caused by representation collapse:

```json
{
  "score": 0.0,
  "passed": false,
  "failure_mode": "underfit",
  "notes": [
    "collapsed_features",
    "temperature_cancelled"
  ],
  "metrics": {
    "train_feature_variance": 0.000002,
    "test_feature_variance": 0.000001,
    "prediction_entropy": 0.02
  },
  "checks": {
    "training_completed": true,
    "artifact_found": true,
    "non_collapsed_features": false,
    "temperature_sensitive": false,
    "queue_wraparound": true
  }
}
```

The judge also records its own phase/check trace in `result["events"]`. Every environment is
stateful: the agent-side tools (`run_train`, `run_eval`, `inspect_logs`, and any
env-specific tools) append structured JSONL to `/workspace/logs/events.jsonl`,
which `inspect_logs.py` summarizes with the train/eval logs to give a replayable
history of tool calls, warnings, and dead ends.

**Limits.** This is not a formally verified sandbox; treat it as an evaluation
harness, not a secure arbitrary-code platform. Some correct fixes are known ML
patterns (e.g. swapping flatten for global pooling in `glyph`) that interacting
bugs and naming abstraction discourage but cannot fully eliminate. The default
Dockerfiles use CPU-only PyTorch. For GPU acceleration, use `shared/Dockerfile.gpu`
which installs CUDA-enabled PyTorch via a build argument (`ARG TORCH_INDEX`).

---

## Running tests

```bash
pip install -r requirements.txt
pytest -q
```

The tests verify that configs parse, path traversal and unresolved placeholders
are rejected, every environment generates, and generated Python compiles with no
leftover placeholders.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on adding new environments, reporting issues, and improving the codebase.

---

## Releases

Stable releases are tagged on GitHub. To pin to a specific version:

```bash
git checkout v0.1.0  # Example: check out a tagged release
```

For the latest features, use the `main` branch. See [GitHub Releases](https://github.com/StrangeTcy/rl_eval_generator/releases) for changelogs.

---

## Example trace

A hand-authored RoPE hard-mode demonstration is provided under `examples/`. It
shows the reset/step runner, paper extraction attempts, section reads, diagnostic
runs, log inspection, and a reference patch application. The trace is a
demonstration of environment dynamics, not a claim about any model.

```bash
bash examples/rope_hard_demo.sh
```

This writes:

```text
examples/rope_hard_reference_human_trace.jsonl
```

The reference patch is stored at:

```text
examples/rope_hard_solution.patch
```

---

## Adding an environment

1. Create `envs/&lt;name&gt;/config.yaml`.
2. Add templates under `envs/&lt;name&gt;/files/`.
3. Define patchable files and allowed imports via config constants.
4. Write an environment-specific `judge.py` using `shared/judge_lib.py`.
5. Run `pytest -q` and generate a smoke environment.

If you need real templating logic, use Jinja2 and a different generator. This generator deliberately stays simple.

---

## License

MIT
