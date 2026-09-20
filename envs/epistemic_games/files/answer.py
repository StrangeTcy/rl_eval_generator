"""Submit your answer to the epistemic task described in task.md.

Edit ONLY this file. Fill in the ANSWER dictionary with your conclusions:

- "posterior_world1": your estimate of P(world 1 | transcript), a number in [0, 1].
  world 1 = the level-1 (genuine) hypothesis, world 2 = the level-3
  (strategic) hypothesis (see task.md).
- "verdict": how strongly the transcript distinguishes the two worlds, using
  the exact vocabulary defined in task.md:
  one of "indistinguishable" | "weakly_distinguishable" | "distinguishable".
- "most_supported": which world the transcript supports: "world1" | "world2" |
  "neither" (use "neither" only when your posterior is exactly 0.5).
- "justification": a short explanation of your reasoning (max 600 characters).

The judge executes this file in an isolated process and reads ANSWER as JSON,
so keep ANSWER JSON-serializable (plain numbers and strings). You may add
helper code above ANSWER to compute your answer, but it must not import
modules outside the allowlist, must not use open/exec/eval, and must
terminate quickly.
"""

VERDICTS = ("indistinguishable", "weakly_distinguishable", "distinguishable")
SUPPORT_OPTIONS = ("world1", "world2", "neither")

ANSWER = {
    "posterior_world1": None,
    "verdict": None,
    "most_supported": None,
    "justification": None,
}
