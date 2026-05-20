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
│   └── moco/
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
```

Generate an environment:

```bash
python generate_env.py \
  --env glyph \
  --name glyph_hard_42 \
  --difficulty hard,hard,hard,hard,hard \
  --seed 42
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
    --difficulty hard,hard,hard,hard,hard \
    --seed "$seed"
done
```

Report the environment, difficulty vector, seed, raw accuracy, and score.

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
