# Getting Started with rl_eval_generator

This guide gets you from clone to a running evaluation in under 5 minutes.

## Prerequisites

- Python 3.11+ (3.13 recommended)
- Docker (for full isolation)
- git

## 1. Clone and Setup

```bash
git clone git@github.com:StrangeTcy/rl_eval_generator.git
cd rl_eval_generator
pip install -r requirements.txt
```

## 2. Verify Installation

Run the test suite to confirm everything works:

```bash
pytest -q
```

All 12 tests should pass.

## 3. Generate Your First Environment

Pick an entry-point environment and generate it:

```bash
# For a quick ML debugging task:
python generate_env.py \
  --env glyph \
  --name my_glyph_test \
  --difficulty easy,easy,easy,easy,easy,easy \
  --seed 42

# Or for a weird machine task (latent computation):
python generate_env.py \
  --env regex_state_machine \
  --name my_regex_test \
  --difficulty easy,easy \
  --seed 42
```

This creates a directory (`my_glyph_test/` or `my_regex_test/`) with:
- `prompt.md` - The task description
- Source files to edit
- `run_eval.sh` - Launch script
- `visible_tests.py` - Tests you can run

## 4. Run the Environment

```bash
cd my_glyph_test
./run_eval.sh
```

This starts an interactive shell in an agent container. Inside:

```bash
# Read the prompt
cat prompt.md

# Edit files with your preferred editor
# (vim, nano, etc. are available)

# When done, submit:
python /tools/submit.py
exit
```

The judge container will evaluate your changes and output a JSON result with your score.

## 5. Quick Non-Interactive Test

For faster iteration without Docker, use the env_runner:

```bash
# Reset an episode
python env_runner.py reset \
  --env glyph \
  --episode-id test_run \
  --difficulty easy,easy,easy,easy,easy,easy \
  --seed 42

# Take actions (read file, edit, etc.)
python env_runner.py step \
  --episode test_run \
  --action '{"type":"read_file","path":"prompt.md"}'

# Submit and get score
python env_runner.py step \
  --episode test_run \
  --action '{"type":"submit"}'
```

## 6. Explore Other Environments

List available environments:

```bash
ls envs/
```

See difficulty axes for any environment:

```bash
python generate_env.py --env glyph --list-axes
python generate_env.py --env regex_state_machine --list-axes
```

Recommended starting points:
- **glyph** - Classic ML debugging (6 axes)
- **batchnorm_ema** - Optimizer/state interaction (5 axes)
- **regex_state_machine** - Latent computation in regex (2 axes)
- **sql_fixed_point** - Graph reachability via SQL (2 axes)

## Next Steps

- Read the full [README.md](README.md) for architectural details
- Check [examples/](examples/) for reference solutions
- See [CONTRIBUTING.md](CONTRIBUTING.md) to add new environments

## Troubleshooting

**Docker fails to build:** Ensure Docker is running and you have enough disk space (environments need ~2-5GB).

**Tests fail:** Run `pip install -r requirements.txt` and ensure Python >= 3.11.

**Generation errors:** Check that all placeholders in config.yaml are defined.
