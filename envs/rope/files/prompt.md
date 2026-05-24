# Task: Fix RoPE from a Paper Excerpt

Your workspace is `/workspace/`.

You are given a paper artifact and a small repository implementing rotary
position embeddings across a few files. The implementation passes some
short-context checks but is wrong for the full algorithm and cached/chunked use.

Fix the implementation.

%%PROMPT_TOOL_HINT%%

## Constraints

- Modify only `rope.py`, `attention.py`, and `cache.py`.
- Do not change public method names.
- Do not modify `model.py`, `train.py`, `eval.py`, or `visible_tests.py`.
- Do not add dependencies.
- Submit with `python /tools/submit.py`, then exit.
