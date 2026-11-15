# Task: Fix RoPE from a Paper Excerpt

Your workspace is `/workspace/`.

You are given a paper artifact and a small repository implementing rotary
position embeddings across a few files. The implementation passes some
short-context checks but is wrong for the full algorithm and cached/chunked use.

Fix the implementation.

%%PROMPT_TOOL_HINT%%

Local diagnostics check finite examples, norms, and consistency between calling
conventions. Passing them does not establish the full transform. The hidden
judge compares with the paper's transform across even head dimensions, bases,
absolute positions, and long sequences. Elementwise comparisons allow absolute
and relative tolerance `2e-4`; long-context integration allows error below `1e-3`.
Acceptance depends on behavior, without requiring every editable file to change.

## Constraints

- Modify only `rope.py`, `attention.py`, and `cache.py`.
- Do not change public method names.
- Do not modify `model.py`, `train.py`, `eval.py`, or `visible_tests.py`.
- Do not add dependencies.
- Submit with `python /tools/submit.py`, then exit.
