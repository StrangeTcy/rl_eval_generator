# Composed Momentum State Isolation

Your task is to correct `%%MODEL_CLASS%%` and `MomentumStep` in `optimizer.py`.

Each `MomentumStep(beta)` maintains a separate momentum trajectory for each parameter object. Starting from zero, `update(p, g)` advances that trajectory by `v_next = beta * v_previous + (1 - beta) * g` and returns the new momentum tensor. It must preserve the supplied parameter and gradient tensors. Different instances and distinct parameter objects must evolve independently.

Composing three modules means feeding the output of the first into the second and the output of the second into the third, with each module called once per step. Parenthesizing those calls must preserve their order and result. The judge checks three successive steps, three-module composition, parameter independence, and the recurrence above. This is a state-isolation and sequential-composition task; no general theorem about arbitrary stateful operators is assumed.
