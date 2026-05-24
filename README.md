# Frontier ML Evaluation Environments

Procedurally generated ML debugging environments for evaluating whether AI agents can reason about machine-learning systems, rather than merely retrieving familiar fixes.

The generator creates self-contained, Dockerized evaluation tasks. Each task presents an agent with a realistic codebase that runs, trains, and often appears superficially healthy, but fails because of subtle interactions between architecture, data, optimization, and stateful training behavior.

---

## Why this exists

Many classic ML debugging benchmarks are now too easy for frontier models. Given a broken CNN on MNIST, a capable model can often ignore the actual failure mode, paste a memorized working architecture, and pass without diagnosing anything.

These environments are designed to make that strategy less reliable:

- bugs interact across files;
- datasets are generated procedurally;
- visible tests can be incomplete or misleading;
- difficulty is configurable along independent axes;
- names and abstractions can be changed to reduce retrieval cues;
- the judge scores held-out behavior rather than trusting agent output.

The goal is to test whether an agent can form and use a causal model of an ML system.

---

## Included environments

### Glyphic Permutation Task (`glyph`)

Synthetic images contain circles, squares, and triangles. A class is defined by the multiset of shapes in the image, not by their spatial locations.

The provided CNN uses a spatially sensitive classifier head. A second optimizer issue prevents convergence. The agent must infer that the task requires spatial invariance and repair both the model and training dynamics.

Difficulty axes:

- architecture clue clarity;
- optimizer pathology;
- augmentation red herring strength;
- visible-test helpfulness;
- data-definition obscurity.

### BatchNorm EMA Corruption (`batchnorm_ema`)

A ResNet-style model trains with gradient accumulation. The loss curve looks healthy, but generalization is poor because BatchNorm running statistics update once per forward pass, not once per optimizer step.

The agent must understand the interaction between gradient accumulation and BatchNorm EMA state, then scale or otherwise control BatchNorm momentum.

Difficulty axes:

- hint visibility;
- DDP/no-sync red herring strength;
- visible-test helpfulness;
- dataset complexity.

### MoCo Representation Collapse (`moco`)

A MoCo-style contrastive learner trains without crashing, but its frozen backbone produces collapsed features.

The bugs are:

1. temperature is applied before normalization, so it cancels out;
2. queue updates silently truncate instead of wrapping around.

Difficulty axes:

- naming abstraction;
- distractor strength;
- queue/batch-size arithmetic;
- temperature bug visibility;
- visible-test helpfulness.

### RoPE Paper-to-Implementation (`rope`)

A compact paper-to-code environment. The agent receives a fake PDF artifact,
stateful paper-reading tools, train/eval diagnostic tools, and a partially
incorrect RoPE implementation in `model.py`. The solution path now requires
extracting and inspecting paper sections, forming an implementation hypothesis,
running diagnostics, reading logs, and revising the patch. Hidden judge tests
check long-context numerical equivalence, offset correctness for KV-cache-style
decoding, norm preservation, and a relative-position property.

**Core bugs:** adjacent even/odd coordinate pairing is implemented incorrectly,
position offsets are ignored during chunked decoding, and hard variants also use
a plausible but wrong frequency scaling.

**Seven axes:** paper clarity · implementation obfuscation · notation mismatch ·
visible-test strength · hidden long-context severity · interaction depth ·
investigation difficulty.

---

## Repository layout

```text
eval-generator/
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
│   └── rope/
├── tests/
└── .github/workflows/ci.yml
```

Environment-specific files live under `envs/<name>/files/`. Shared tooling is injected from `shared/` when an environment is generated.


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

Generate an environment:

```bash
python generate_env.py \
  --env glyph \
  --name glyph_hard_42 \
  --difficulty hard,hard,hard,hard,hard \
  --seed 42
```

Generate a RoPE paper-to-implementation task:

```bash
python generate_env.py \
  --env rope \
  --name rope_hard_1 \
  --difficulty hard,hard,hard,hard,hard,hard,hard \
  --seed 1
```

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

Supported action types are:

- `shell` / `run` via `{"cmd": "..."}`;
- `read_file`;
- `write_file`;
- `list_files`;
- `submit`.

The runner is intentionally lightweight. It stores episodes under `.episodes/`
and uses the persistent filesystem as environment state. If Docker is available,
`submit` can run the generated Docker judge; otherwise it terminates with a clear
observation explaining that terminal Docker scoring is unavailable locally.

### Runner limitations

This is a prototype interaction wrapper, not a full RL runtime. Current
limitations:

- actions are coarse shell/file operations rather than a typed editing API;
- observations are command output strings;
- rewards are sparse and terminal by default;
- the local runner does not maintain a persistent container session;
- parallel rollouts are not yet implemented;
- strict resource limits are provided by Docker only when using generated
  `run_eval.sh`;
- terminal scoring requires Docker on the host.

These limitations are deliberate for a first version. The next natural step is a
persistent-container backend with batched rollouts and stricter action budgets.

---

## Generator design

Templates use `%%PLACEHOLDER%%` syntax. The generator performs string substitution only. It intentionally does not implement conditionals, loops, includes, filters, or inheritance.

Important generator safeguards:

- strict unresolved-placeholder errors;
- recursive substitution for composed values;
- indentation-preserving multiline substitutions;
- output path containment checks;
- atomic generation through a temporary directory;
- UTF-8 file I/O;
- symlink rejection;
- config validation before writing files.

---

## Benchmark integrity model

The agent submits a unified diff patch. The judge applies the patch to pristine sources, validates patched files, and runs training/evaluation in subprocesses.

The source validator uses an allowlist of permitted imports and rejects obvious benchmark-bypass constructs such as `exec`, `eval`, `compile`, `__import__`, and `open`.

For scoring, judges use a separation-of-evaluation pattern where possible:

1. train patched code in a subprocess;
2. scrub unexpected runtime-written files;
3. generate held-out inputs and labels in the trusted judge process;
4. expose only unlabeled inputs to the model subprocess;
5. compute the score in the judge process.

This substantially reduces common reward-hacking routes such as stdout spoofing, direct hidden-label reads, and judge-process code execution.

It is **not** a formal Python sandbox. Docker isolation is the primary security boundary. AST validation is a benchmark-integrity layer, not a substitute for container isolation.

---

## Failure mode reporting

Judges emit a structured `failure_mode` in addition to scalar `score`. The common
vocabulary is:

- `pass`
- `patch_missing`
- `patch_invalid`
- `source_invalid`
- `training_failed`
- `artifact_missing`
- `runtime_error`
- `timeout`
- `underfit`
- `overfit_visible_tests`
- `specification_gaming`
- `reward_denial`
- `unknown`

The result JSON also contains `checks` and `metrics` dictionaries where judges
record anti-gaming signals such as prediction entropy, predicted-class coverage,
feature variance, local/proxy score gaps, malformed outputs, and hidden check
breakdowns.

This is intended to make failures diagnosable: a low score caused by ordinary
underfitting should look different from a visible-test overfit, malformed output,
or local-proxy exploit.

---

## Running tests

```bash
pip install -r requirements.txt
pytest -q
```

The tests verify that:

- configs parse;
- path traversal is rejected;
- unresolved placeholders fail;
- all included environments generate;
- generated Python files compile;
- generated files contain no unresolved placeholders.

---

## Multiple seeds

Use seeds to generate multiple instances at the same difficulty:

```bash
for seed in 1 2 3 4 5; do
  python generate_env.py \
    --env moco \
    --name "moco_hard_${seed}" \
    --difficulty hard,hard,hard,hard,hard,hard,hard \
    --seed "$seed"
done
```

Report the environment, difficulty vector, seed, raw accuracy, and score.

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

## Known limitations

### Goodhart's Law

Some correct fixes are known ML patterns. For example, replacing flattening with global pooling can be guessed without fully understanding the glyph data-generating process. The environments reduce this risk with interacting bugs, red herrings, and naming abstraction, but cannot eliminate pattern familiarity.

### Runtime cost

The Dockerfiles install CPU-only PyTorch. Hard CIFAR-based variants may be slow on modest hardware.

### Security scope

The judge containers are hardened, but this is not a formally verified sandbox. Treat the benchmark as an evaluation harness, not as a secure arbitrary-code execution platform.

---

## Adding an environment

1. Create `envs/<name>/config.yaml`.
2. Add templates under `envs/<name>/files/`.
3. Define patchable files and allowed imports via config constants.
4. Write an environment-specific `judge.py` using `shared/judge_lib.py`.
5. Run `pytest -q` and generate a smoke environment.

If you need real templating logic, use Jinja2 and a different generator. This generator deliberately stays simple.

---

## License

MIT
