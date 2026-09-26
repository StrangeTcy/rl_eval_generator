# Frontier ML Evaluation Environments

[![CI](https://github.com/StrangeTcy/rl_eval_generator/actions/workflows/ci.yml/badge.svg)](https://github.com/StrangeTcy/rl_eval_generator/actions/workflows/ci.yml)

Procedurally generated ML debugging environments for evaluating whether AI agents can reason about machine-learning systems, rather than merely retrieving familiar fixes.

> **Judge-validation coverage (2026-09-26):** GitHub CI has two jobs: `smoke` installs `requirements.txt` (no PyTorch, so PyTorch-dependent behavioral tests **skip** there, and its Docker step builds images without executing judges) and `behavioural` installs pinned CPU PyTorch/Torchvision and runs the full behavioral suite including the opt-in slow oracles with zero torch skips. A green `smoke` badge alone does not establish PyTorch or all-instance behavioral coverage. Local PyTorch checks and exact-instance, provider-free oracle results are described in [safe suite execution](docs/suite_execution.md), and judge bug history in [the calibration log](docs/judge_calibration.md). An unconfigured or failing reference blocks paid suite/pilot/direct-episode calls, including with `--allow-compile-only-oracles`. Historic pilot patches and trajectories were not available for offline re-scoring; the recorded pilot scores are not a model-ability finding.

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

## Evaluation target: structural awareness, not scalar intelligence

This suite is not designed to produce a single intelligence score. A recurring
target is **metis**: the ability to notice the structure generating the presented
task, preserve invariants across representation changes, resist misleading
frames, and exploit valid alternative formulations.

The benchmark question is not only how hard a model pushes on the front door,
but whether it notices the wall next to the lock. Controlled comparisons use
same-semantics/different-syntax cases, narrative-versus-bare evidence,
matched rollout controls, witness-valid versus witness-broken shortcuts, and
explicit resource protocols. Results are behavioral sensitivities to named
interventions, not direct measurements of scalar intelligence or hidden model
architecture. See [`docs/metis.md`](docs/metis.md) for the taxonomy and
interpretation rules.

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

### Recurrent-depth environments (`envs/recurrent_depth/`)

The `rd_state_carry`, `rd_adaptive_halting`, and `rd_gradient_credit` families test behavioral invariants under increasing recurrence depth. They exercise state reuse, per-example halting masks, and autograd credit assignment with tiny CPU tensors. These are black-box behavioral tasks: a score at depth 64 does **not** establish that a model used recurrent computation internally.

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
│   ├── recurrent_depth/
│   │   ├── state_carry/
│   │   ├── adaptive_halting/
│   │   └── gradient_credit/
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

## Stateful environment runner

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
pristine sources and runs the generated judge either locally (`--sandbox local`)
or in the generated no-network judge image (`--sandbox docker`). It does not
require the interactive `run_eval.sh` flow.

Rewards are terminal and the local runner is single-session. The Docker mode
uses the same read-only root, dropped-capability, no-network, PID, memory, CPU,
and tmpfs restrictions as the automated arena.

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

## Provider-neutral automated arena

`arena.py` keeps the model controller on the host and runs generated environment
commands in a no-network Docker container. OpenRouter, Hugging Face Inference
Providers, and custom OpenAI-compatible endpoints all use `POST
{api_base}/chat/completions`.

```bash
export OPENROUTER_API_KEY="..."
python arena.py run \
  --provider openrouter \
  --model openai/gpt-5.6-sol \
  --env rd_state_carry \
  --difficulty hard,hard,hard,hard,hard \
  --seed 42 \
  --max-steps 40 \
  --max-tokens 2048 \
  --temperature 0 \
  --sandbox docker \
  --out runs/
```

Use `--provider huggingface --model openai/gpt-oss-120b` with `HF_TOKEN` for
Hugging Face, or `--provider custom --api-base URL --api-key-env API_KEY` for a
compatible endpoint. `--api-key` is supported for automation, but environment
variables are safer because shell arguments can appear in history and process
listings. Keys are not put into traces, manifests, Docker environment variables,
or container command lines.

Each run directory contains `manifest.json`, `trace.jsonl`,
`model_responses.jsonl`, `api_errors.jsonl`, `submission.patch`,
`workspace.diff`, judge stdout/stderr, and the final judge JSON. Summarize a run
with:

```bash
python arena.py summarize runs/<run-id>
```

The legacy `run_hf_episode.py` flags remain available as a wrapper, but it now
uses the same chat-completions path and no longer makes an implicit legacy HF
fallback request.

### Trajectory-semantics direct-answer benchmark

The primary relay benchmark is a host-side direct-answer evaluation, not a task
where the model writes a solver. It keeps rollout horizon, query-specific
computation, representation, query-specific witness status, and the answer-only
versus external-scratchpad resource protocol as separate metadata. It includes
flat and operationally reflective relay presentations, parse-only/one-step/
state-at-horizon/template-return/complete-state-return controls, semantic
relabelings, format-only variants, and matched horizons such as `6, 30, 126,
510`. Its summaries report behavioral accuracy and stale-witness diagnostics;
they do not produce an aggregate depth score or an internal-algorithm claim.

```bash
export OPENROUTER_API_KEY="..."
python arena.py trajectory \
  --provider openrouter \
  --model openai/gpt-5.6-sol \
  --out runs/trajectory-demo \
  --system-seeds 0:3 \
  --initial-state-seeds 0:0,0,0,0 \
  --presentation-seeds 1000:1003 \
  --resource-protocol answer_only \
  --max-calls 1632

# Or inspect the exact request budget before resolving credentials.
python arena.py trajectory-plan \
  --provider openrouter --model openai/gpt-5.6-sol \
  --system-seeds 0:3 --initial-state-seeds 0:0,0,0,0 \
  --max-tokens 64 --confirm-calls 1632

python arena.py trajectory-analyze runs/trajectory-demo
```

The controller and API key stay on the host. `cases.jsonl` is the private case
record, while `trace.jsonl`, `answers.jsonl`, `model_responses.jsonl`, and
`api_errors.jsonl` retain prompts, raw outputs, parsed answers, correctness,
retry/error information, latency, usage, and provider metadata with secret
redaction. Controls are query-conditioned: parse-only cases use horizon `0`,
one-step cases use horizon `1`, and only trajectory queries expand across the
requested horizon list. `matched_control_id` joins parse and one-step controls
to the same trajectory condition without pooling valid and witness-broken
siblings. Each trajectory result records `parse_control_passed` and
`one_step_control_passed` for the same API replication; the conditional summary
table includes only rows where both controls passed and reports the
unconditional trajectory estimand plus included, failed-control, missing-control,
and excluded counts for the conditional estimand. Missing controls from a
truncated run remain `null`, not failures. Control status separates `passed`,
`failed`, `missing`, and `api_error`; an empty conditional sample is reported
as `null`/`NA`, not zero.

Every answer record also has an exclusive `response_status`: `answered`,
`api_error`, `parse_error`, or `judge_error`; an API failure, unparseable answer
format, or scorer failure is not an observed answer. `trajectory_attempts` counts every
trajectory request, while `trajectory_observed_cases` counts only `answered`
responses. The summary reports separate API, parse, and judge error counts and
uses `unconditional_trajectory_accuracy_observed` and
`conditional_trajectory_accuracy_observed` for model accuracy; those rates have
only observed, answerable cases in their denominators. `trajectory_success_per_attempt`
is an operational availability metric, not model accuracy. The partition is
applied in this order: trajectory-response error (`api_error`, then
`parse_error`, then `judge_error`), control `api_error`, missing control,
observed control failure, and finally included (both same-replication controls
passed). Thus a trajectory API timeout is never relabeled as a missing or
failed control, even if both controls passed. Provider error evidence takes
precedence over a contradictory explicit `control_status`; malformed status
values are rejected. Conditional accuracy remains accuracy among trials whose
same-replication controls passed, not an automatic adjustment for parsing
difficulty.


Use `--judge host`, `--judge docker`, or `--judge both`. The latter fails if
host and offline Docker judgments disagree. The optional
`docker/Dockerfile.trajectory_judge` image evaluates private case/answer records
offline with `--network none`; it has no provider client and never receives an
API key. `trajectory-plan` estimates calls and maximum output-token budget
without resolving credentials, and a live trajectory run requires either
`--max-calls` or an exact `--confirm-calls` guard.

The `ts_parse_only`, `ts_one_step`, and `ts_trajectory` generated environments
are a separate solver-synthesis/debugging track. Their judge scores must remain
separate from direct-answer results and are not evidence that a model used
recurrent internal computation.

For a depth comparison, keep the model version, prompt, output-token limit,
maximum tool steps, judge budget, and environment seeds fixed while varying only
the recurrence-depth axis. Use multiple seeds and report invalid-action failures
separately from incorrect repairs. Useful derived metrics include
`pass_rate_by_depth`, `mean_score_by_depth`, `maximum_reliably_solved_depth`,
`output_tokens_per_score`, `tool_steps_per_score`, `latency_per_score`, and a
failure-mode distribution. These tasks measure behavioral robustness and cost or
latency scaling; a black-box result cannot prove that the model used recurrent
depth internally.

---

## Suite inventory, checkpointed execution, and constrained notebooks

The repository has two separate scales: an environment name is one declarative
config, while a difficulty vector and seed are an evaluation case. The suite
runner never silently treats one representative case as coverage of every
variant. The current registry and config audit are written by
`tools/suite_inventory.py`:

```bash
# No provider calls. One representative vector per environment.
python tools/suite_inventory.py --out suite_manifest.json

# Expand every declared difficulty-axis Cartesian product and two seeds.
python tools/suite_inventory.py \
  --out suite_all.json --matrix all --seeds 0,1

# Also generate and compile every planned case, still without a model or Docker.
python tools/suite_inventory.py \
  --out suite_preflight.json --matrix all --seeds 0 --preflight
```

The manifest records the repository commit, dirty-worktree state, config hashes,
tracks, axis levels, registry mismatches, and explicit cases. A clean audit is a
precondition for scheduling. In this checkout the registry currently contains
33 named config entries; use the generated manifest rather than assuming a
number when newly authored environments are present.

`tools/run_suite.py` wraps the existing `arena.py run` controller. It runs one
case at a time, records model failures as scored results, pauses on provider or
infrastructure failures, and atomically checkpoints after each completed case:

```bash
python tools/run_suite.py \
  --manifest suite_all.json \
  --out runs/suite-groq \
  --provider custom \
  --api-base https://provider.example/v1 \
  --model provider/pinned-model \
  --api-key-env SUITE_API_KEY \
  --sandbox docker \
  --max-cases 1 \
  --max-api-calls 100
```

The key is read by the host controller only. The scheduler passes an environment
variable name, never a literal key, and the existing controller removes
provider-looking variables before invoking environment subprocesses. Provider
profiles and the optional local `secret_key.json` loader are documented in
[`docs/secrets.md`](docs/secrets.md) and [`docs/free_providers.md`](docs/free_providers.md);
run `tools/provider_preflight.py` before enabling a provider. Use a new
output/checkpoint directory when changing provider, model, sandbox, or manifest;
checkpoint metadata rejects accidental mixing. `coverage.json`, `coverage.csv`,
and `coverage.md` distinguish scored, blocked, paused, and infrastructure cases.
`--dry-run` plans a bounded batch without requiring an API key. Live runs now
block before provider access if the oracle report lists unverified judges:
compiling a judge is not proof that it grades correctly. See
[`docs/suite_execution.md`](docs/suite_execution.md) for offline behavioral
checks and the explicit, risk-accepting `--allow-compile-only-oracles` override.

`tools/notebook_mode.py` reports dependency, Docker, memory, disk, GPU, and
notebook-runtime capabilities without executing generated code. The notebook
`notebooks/run_all_envs.ipynb` is a controller frontend, not a sandbox: it runs
only inventory and preflight when Docker is unavailable. The canonical manual
GitHub Actions workflow is `.github/workflows/evaluate-suite.yml`; it uses a
standard Docker runner, a pinned model/provider supplied at dispatch, a bounded
batch, and uploads only the manifest, checkpoint, capability report, and
coverage summaries. Configure a `SUITE_API_KEY` repository secret for the host
controller; it is not mounted into agent or judge containers. A workflow batch
must be resumed with the same manifest/provider/model contract rather than
rotating providers mid-experiment.

This scheduler supports coverage accounting, not a claim that all tasks are
comparable. Keep direct-answer, solver-synthesis, recurrent-depth, and ML
repair tracks separate in analysis, and distinguish “attempted every planned
case” from “every case received a scored result.”

For the bounded NVIDIA-first five-case handoff, use the exact profile and
provider-free preparation path in [`docs/first_nvidia_pilot.md`](docs/first_nvidia_pilot.md).
It does not make model-availability or free-entitlement claims and never
switches providers automatically.

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
