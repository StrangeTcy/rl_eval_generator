# Judge correctness hotfix

Date: 2026-10-16.
Branch: `arena/1ddc930c-rl-eval-generator`.
Starting HEAD: `a15d2d9c39860bc3bc4e7d21cf43f60e6178c2e8` (clean).
This is not a benchmark redesign. No campaigns, no paid APIs, no new envs.

## 1. Epistemic Boolean coercion — reproduced, then fixed

Against HEAD `a15d2d9` before the patch:

```
model = example_visible_model()
query_value(model) is True
verify_certificate(model, {"query_value": "false"})
# -> (True, "ok")
```

Cause: `bool(raw["query_value"]) != bool(true_q)` treats any nonempty string
as true. The same `bool()` path applied to `bundle_possible`, so `0` was
accepted as false and `1` / `"true"` as true.

Fix: `_require_bool` accepts a field only when `type(value) is bool`.
After the fix:

```
verify_certificate(model, {"query_value": "false"})
# -> (False, "query_value must be a bool, got str")
verify_certificate(model, {"query_value": True})
# -> (True, "ok")
```

Output schema unchanged. `joint_world` / `joint_inner` remain strings.

## 2. Checker independence

Shared **trusted** oracles (not a defect by themselves):

- `query_value` / `eval_formula` — nested product Kripke evaluation
- `flatten_model` — explicit global worlds = chains (depth-1 self-check
  inside `verify_certificate`; tests also compare on ≥40 models)
- `bundle_possible` / cell intersection — finite set intersection
- `reference_certificate` builds a witness from those oracles; the judge
  does not need to call it, and tests still confirm it is not named in
  `verify_certificate`. Calling a trusted oracle is not calling the
  candidate.

Independent of the **candidate solver**:

- AST of `network.py` and `judge.py` has no `import solver`
- `sys.modules["solver"]` replaced with a boom module; `verify_certificate`
  still decides
- Bundle possibility is recomputed in the test by intersecting blocks
  without calling `bundle_possible`, then compared
- `"false"`, `0`, `1`, `None`, `[]`, `{}` are rejected even when their
  truthiness matches the correct Boolean

## 3. Maze remaining-depth discrepancy — reproducible on a schema-valid fixture

`_neighbours` emits `descend` only if `remaining >= 1`. `replay_route` did
not. Generator mazes never place shafts on a remaining-0 tile (children
are shaftless `crypt`/`pit`). A **hand-written** maze whose shaft child
itself has shafts, with `depth=1`, enters that child at remaining=0.

Before the patch, this illegal route replayed as `(True, "ok")` and
`verify_certificate` accepted it, while BFS neighbours at that state
offered only `move`. After the patch:

```
replay_route(...) -> (False, "step 2: nesting depth exhausted")
```

Legal generated SAT routes still replay. Generator was not changed.

## 4. Tests

```
.venv/bin/python -m pytest tests/test_recursive_epistemic_gluing.py \
  tests/test_recursive_maze_gluing.py tests/test_recursive_distributed_gluing.py \
  tests/test_recursive_gluing.py tests/test_recursive_gluing_discovery.py \
  tests/test_experiment_arms.py tests/test_latent_registry.py -q
```

105 passed, 0 skipped.

Files changed: epistemic `network.py`, maze `network.py`, the two family
test modules, this note. Untouched: v0, discovery, distributed, campaigns.
