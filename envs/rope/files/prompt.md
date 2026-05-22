# Task: Fix RoPE from a Paper Excerpt

Your workspace is `/workspace/`.

You are given a paper artifact and a small implementation of rotary position
embeddings in `model.py`. The implementation passes some short-context checks but
is wrong for the full algorithm.

Fix the implementation.

%%PROMPT_TOOL_HINT%%

## Constraints

- Modify only `model.py`.
- Do not change public method names.
- Do not modify `train.py`, `eval.py`, or `visible_tests.py`.
- Do not add dependencies.
- Submit with `python /tools/submit.py`, then exit.
