# Nested situations

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one finite nested situation:

- `agents`: list of agent names.
- `frames`: mapping from frame name to
  `{"worlds": [...], "atoms": {atom: [world, ...]}, "indist": {agent: [[world, ...], ...]}}`.
  `indist[agent]` is a partition of that frame's worlds: the agent cannot tell
  worlds in the same block apart.
- `levels`: a list of frame names, outermost first. A global situation is a
  chain of worlds, one from each level.
- `actual`: the actual chain (same length as `levels`).
- `query`: an atom (string), or a list
  `["not", φ]`, `["and", φ, ψ]`, or `["K", agent, φ]`.
- `bundle`: `null`, or a map `{agent: world}` of proposed worlds in the
  **outermost** frame.

An atom holds at a chain if it holds at any world of the chain in the frame
that lists it. `K_agent φ` holds at a chain `c` exactly when `φ` holds at every
chain `c'` such that, at every level, `c` and `c'` lie in the same
indistinguishability block for that agent.

If `bundle` is not `null`, it is **possible** when the intersection of the
outermost-frame indistinguishability blocks containing those worlds is
nonempty. Each listed world is itself a legal local view; that does not mean
the views occur together.

## Output

```python
{"query_value": True or False}
{"query_value": True or False, "bundle_possible": True or False}
```

Include `bundle_possible` if and only if `bundle` is not `null`. A crash,
timeout, or parse failure is not a truth value. `solve` must be deterministic.

## What "correct" means

The actual chain can satisfy an atom while an agent does not know it.
Truncating the chain (ignoring inner frames) can change a nested `K` query.
Two agents can each have a nonempty local block whose intersection is empty.

## Visible checks

```bash
python visible_tests.py
```
