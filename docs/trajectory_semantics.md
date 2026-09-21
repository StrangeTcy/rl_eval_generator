# Trajectory-semantics family

> **Metis move tested:** representation invariance, shortcut recognition, and shortcut invalidation.

The trajectory-semantics family tests whether an agent preserves a transition
invariant when the same relay system is presented in flat or reflective syntax,
under semantic relabeling, and with format-only noise. Valid and broken witness
siblings test whether the agent recognizes when a tempting shortcut is no
longer licensed by the query-specific structure.

The direct-answer benchmark is controlled separately from the generated
solver-synthesis environments. Parse-only and one-step cases are matched
controls for longer trajectory queries; they are not pooled into a depth score.
Use the host-side runner and its paired-control analysis:

```bash
python arena.py trajectory-plan \
  --provider custom --api-base https://provider.example/v1 \
  --model provider/pinned-model --system-seeds 0:3 \
  --initial-state-seeds 0:0,0,0,0 --max-tokens 64
```

The generated configs live under `envs/trajectory_semantics/`. The primary
interpretation and taxonomy are in [`metis.md`](metis.md), while execution,
replication, API-error, and conditional-control rules are in
[`suite_execution.md`](suite_execution.md) and the trajectory runner.

Interpret results as behavioral sensitivity to the named representation,
witness, horizon, and resource interventions. A trajectory result does not
establish serial internal depth or recurrent model architecture.
