# Nested situations

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one finite nested situation:

- `agents`: list of agent names (two or more).
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
- `nested_bundle`: `null`, or a map `{agent: world}` of proposed worlds in the
  **second** frame (`levels[1]`), when that frame exists.

An atom holds at a chain if it holds at any world of the chain in the frame
that lists it. `K_agent φ` holds at a chain `c` exactly when `φ` holds at every
chain `c'` such that, at every level, `c` and `c'` lie in the same
indistinguishability block for that agent.

If `bundle` is not `null`, it is **possible** only when some outermost-frame
world lies in **every** listed agent's block (not merely every pair of agents).
If `nested_bundle` is also present, the same check is required independently
on the inner frame, and both checks must succeed. A named world that does not
belong to that frame, or that does not appear in that agent's partition, is
not a legal local view.

Each listed world can be a legal local view by itself. That does not mean the
views occur together. Ignoring inner frames can change both a nested `K`
query and a `nested_bundle` check.

## Output

```python
{"query_value": True or False}
{"query_value": True or False, "bundle_possible": True or False}
{"query_value": True or False, "bundle_possible": True, "joint_world": "w", "joint_inner": "u"}
```

Include `bundle_possible` if and only if `bundle` or `nested_bundle` is not
`null`. If you claim `bundle_possible` is true, you must also name a
`joint_world` that lies in every outermost block you used. If `nested_bundle`
is present and you claim true, you must also name `joint_inner` for the inner
frame. A crash, timeout, or parse failure is not a truth value. `solve` must
be deterministic.

## What "correct" means

The actual chain can satisfy an atom while an agent does not know it.
Truncating the chain (ignoring inner frames) can change a nested `K` query
and can hide an inner conflict among local views.
Two, three, or four agents can each have a nonempty local block such that
every pair (and even every triple) of blocks overlap, while no world lies in
all of the blocks at once.

## Visible checks

```bash
python visible_tests.py
```
