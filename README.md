# Frontier ML Evaluation Environments

Procedurally generated ML debugging environments for evaluating whether AI agents can reason about machine-learning systems, rather than merely retrieving familiar fixes.

The generator creates self-contained, Dockerized evaluation tasks. Each task presents an agent with a realistic codebase that runs, trains, and often appears superficially healthy, but fails because of subtle interactions between architecture, data, optimization, and stateful training behavior.

### Environment Categories

*   **Research-Style ML Debugging:** `glyph`, `batchnorm_ema`, `moco`
*   **Paper-to-Code & Stateful Investigation:** `rope`
*   **Compositional & Category-Theoretic Reasoning:** `cat_theo/*` (17 environments)
    > *These tasks target compositional invariants that current transformer-family models routinely violate under composition, batching, symmetry, and state.*

### Recommended Entry Points

*   **MoCo** for testing realistic, multi-file ML debugging.
*   **RoPE** for testing paper-to-implementation reading and offset calculations.
*   **tensor_functor** or **equivariant_diagram** (in `envs/cat_theo/`) to test category-theoretic compositionality.

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
│   └── cat_theo/
│       ├── <individual_ct_envs>/
│       ├── semiring/
│       │   ├── gnn_message_passing/
│       │   ├── ssm_parallel_scan/
│       │   └── neuro_symbolic_parser/
│       └── sheaf/
│           ├── sheaf_schema_sync/
│           ├── sheaf_invariant_gluing/
│           └── sheaf_physical_constraints/
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
bugs and naming abstraction discourage but cannot fully eliminate. The
Dockerfiles use CPU-only PyTorch, so hard CIFAR-based variants are slow on modest
hardware.

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
