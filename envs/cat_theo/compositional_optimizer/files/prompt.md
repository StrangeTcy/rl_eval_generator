# Sequential Momentum State Isolation

Your task is to correct the modular optimizer blocks in `optimizer.py`.

`MomentumStep.update(p, grad)` returns the updated momentum `v = beta * v + (1 - beta) * grad`, starting from zero for each parameter. Each instance must maintain its own momentum for each parameter object. Updating one parameter or optimizer must not alter another's state or mutate `p` or `grad`.

The judge chains three instances, repeats updates while applying a learning rate of `%%LR_VAL%%`, and interleaves another parameter. Implement state isolation and the stated numerical recurrence. This interface exposes sequential updates rather than a separate composition object.
