# Contributing to rl_eval_generator

We welcome contributions! This document explains how to add new environments, report issues, and improve the existing codebase.

## Reporting Issues

Before filing an issue:
1. Check existing issues for duplicates
2. Include:
   - Environment name
   - Difficulty vector
   - Seed value
   - Full error output
   - Steps to reproduce

## Adding a New Environment

The fastest way to understand the structure is to examine existing environments:

```bash
# Look at a simple environment
ls -R envs/glyph/

# Look at a weird_machine environment
ls -R envs/weird_machine/regex_state_machine/
```

### Step-by-Step Guide

1. **Create the environment directory**
   ```bash
   mkdir -p envs/my_new_env/files
   ```

2. **Create `config.yaml`**
   
   Minimum structure:
   ```yaml
   name: my_new_env
   description: One-sentence description of the task
   
   axes:
     - name: difficulty_axis_1
       description: What this axis controls
       values:
         - easy
         - medium
         - hard
     - name: difficulty_axis_2
       description: Another axis
       values:
         - easy
         - hard
   
   scoring:
     mode: continuous_accuracy
     pass_threshold: 0.85
     partial_threshold: 0.60
   
   constants:
     %%MODEL_FILE%%: "model.py"
     %%PATCHABLE_FILES%%: "model.py,train.py"
     %%EXTRA_ALLOWED_IMPORTS%%: ""
   ```

3. **Create template files under `files/`**
   
   Required:
   - `prompt.md` - The task presented to the agent
   - At least one Python file (usually matching `%%MODEL_FILE%%`)
   - `judge.py` - The evaluation logic
   - `visible_tests.py` - Tests the agent can run
   
   Use `%%PLACEHOLDER%%` syntax for values that should be substituted:
   ```python
   # In model.py
   MAX_ITER = %%MAX_ITER%%
   ```

4. **Write the judge**
   
   Use `shared/judge_lib.py` for common utilities:
   ```python
   from judge_lib import *
   
   def judge(workdir, seed, difficulty, **kwargs):
       result = base_result()
       # Your evaluation logic here
       # Use emit(), set_metric(), set_failure()
       # Return result dict
   ```

   Judges should:
   - Generate held-out test cases
   - Validate the patch touches required files
   - Check for import allowlist violations
   - Emit structured diagnostics on failure
   - Return a score in [0, 1]

5. **Test locally**
   ```bash
   # Generate and verify it compiles
   python generate_env.py --env my_new_env --name test_my_env --difficulty easy,easy --seed 1
   cd test_my_env
   python -m py_compile *.py
   
   # Run the judge directly
   python files/judge.py
   ```

6. **Add tests**
   
   The existing test suite uses `rglob` to find all configs and judges:
   ```bash
   pytest -q
   ```
   
   Your new environment will be automatically picked up if:
   - `config.yaml` exists and is valid
   - `judge.py` exists and is valid Python
   - All placeholders resolve

7. **Document it**
   
   Add your environment to the README:
   - Under the appropriate category in "Environment Categories"
   - In the repository layout diagram
   - Optionally in "Recommended Entry Points"

### Environment Design Principles

**Make retrieval unreliable:**
- Use non-standard variable names
- Add red herrings and distractor code
- Make bugs interact across files
- Use procedural generation for data

**Make gaming difficult:**
- Judge should check held-out behavior
- Validate patch touches intended files
- Use import allowlists
- Emit structured failure diagnostics

**Make it configurable:**
- Each axis should independently affect difficulty
- Provide easy/medium/hard levels
- Document what each axis controls

### Good First Environments

If you're new to the codebase, start with a simple environment based on:
- `envs/glyph/` - Classic ML debugging pattern
- `envs/weird_machine/regex_state_machine/` - Self-contained, no ML dependencies
- `envs/weird_machine/sql_fixed_point/` - Pure logic, no training

## Code Style

- **No emojis** in documentation
- **Short, lowercase commit messages** (e.g., "add new environment", "fix judge scoring")
- **Plain professional headers** (no cutesy ASCII art)
- **Keep README edits concise** - don't double its length

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run `pytest -q` - all tests must pass
5. Generate and test at least one instance of your new/modified environment
6. Update documentation
7. Submit PR with clear title and description

## Review Guidelines

Reviews focus on:
- **Correctness** - Does the judge accurately evaluate solutions?
- **Security** - Are there sandbox escapes or gaming opportunities?
- **Clarity** - Is the prompt understandable? Are failure messages helpful?
- **Configurability** - Do axes meaningfully affect difficulty?

## Maintainers

- Maxim Smirnov <hatguy@yandex.ru>

## License

MIT - see [LICENSE](LICENSE)
