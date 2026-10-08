# Causal experiment families

`rl_eval_generator` now has a provider-free design layer for matched causal
experiments. It describes a task as a latent causal system rather than as an
ordered difficulty or intelligence ladder:

- **latent factors**: task state, causal mechanism, observable state, proxy
  signal, evaluator state, hidden state, and reported agent belief;
- **policies**: observation function, reward/proxy mapping, and evaluator
  policy are declared separately;
- **orthogonal interventions**: presentation, epistemic events, evidence and
  source ecology, attention, evaluator, monitoring, reward proxy, terminology,
  tool interfaces, game models, and strategic depth can be crossed without
  silently changing difficulty;
- **measurements**: terminal outcome and trajectory/process measurements are
  separate, with expected invariances and expected differences recorded;
- **provenance**: experiment digest, twin group, hypothesis, controls,
  measurement IDs, and partner IDs travel with every case.

The initial example uses the existing `epistemic_games` substrate:

```bash
/tmp/rl-eval-venv/bin/python tools/experiment_family.py \
  --spec experiments/epistemic_invariance.yaml \
  --out /tmp/epistemic-family.json
```

The compiler performs no provider calls and starts no Docker containers. The
example is deliberately `design_only`; its output contains
`ready_for_scheduler: false` and each undeclared materializer is listed under
`safety.unmaterialized_interventions`. A scheduler must check this field before
starting an environment or spending provider budget.

The three prioritized basis vectors have a concrete crossed example:

```bash
/tmp/rl-eval-venv/bin/python tools/experiment_family.py \
  --spec experiments/epistemic_basis_axes.yaml \
  --out /tmp/epistemic-basis.json
```

That specification compiles eight cells from the product of public/private
event structure, hypergame/level-k profiles, and static/adaptive information
environments. Each cell gets a baseline and three counterfactual variants,
for 32 design cases total. The profile records an explicit game model, actual
`level_k`, and beliefs about the opponent's depth; the information cell records
horizon, source ecology, state-contingent signalling, endogenous attention,
and negative information. These are crossed basis vectors, not E0-to-E15
intelligence levels.

## Twin contract

`arena.experiment_schema.expand_counterfactual_twins` creates a baseline and
one variant per intervention for each selected inventory case. Every variant
retains the base environment, difficulty vector, and seed. It does not claim an
intervention has been applied: a variant is schedulable only when its
intervention has a declared materializer and the experiment itself is not
`design_only`.

Use `tools/suite_inventory.py` as the source of base cases. This preserves the
existing registry and difficulty-axis architecture while the experiment layer
adds causal metadata on top.

## Canonical trajectories

Run finalization now derives `trajectory.json` and `trajectory_metrics.json`
from `trace.jsonl`. `arena.trajectory_schema` normalizes observations, model
actions, tools, tests, file mutations, rewards, and termination events. The
metrics are observable behavioral summaries, including:

- hypothesis switches and state revisitation;
- action entropy, repeated actions, and backtracking;
- time to the first discriminating test;
- accumulated information gain when an environment reports it;
- explicit proxy-exploitation markers when a reward/proxy evaluator reports them.

These fields are not claims about private chain-of-thought or unobservable
belief. They are canonical, replayable event semantics that can be judged
alongside terminal correctness. Secrets continue to be redacted by the stable
artifact writer.

To attach twin metadata to a direct episode, pass a JSON object through the
existing runner:

```bash
python arena.py run ... \
  --experiment-case '{"experiment_id":"demo","twin_group_id":"g1","variant_id":"baseline"}'
```

The same metadata is accepted by the suite dispatcher when a case row contains
experiment fields. It is persisted in `manifest.json` and is therefore
available when linking hypotheses, controls, measurements, judges, trajectories,
and claims.
