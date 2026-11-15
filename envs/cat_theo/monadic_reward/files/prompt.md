# Monadic Verification & Sandboxing

Your task is to correct the state transition logic `%%MODEL_CLASS%%` in `agent_code.py` using the State Monad defined in `monad.py`.

In verifiable reward harnesses, we want to isolate code execution from external environmental side-effects. We model state transitions purely as a State Monad:
$$S \to (A, S)$$
where $S$ is the log of allowed transitions, and $A$ is the computation output.

`compute(x)` accepts a serialized pair of integers such as `"(10, 20)"`. It returns a State Monad that, when run, yields the first integer plus one and appends `"processed <first integer>"` to the supplied log. Calling `compute` must leave external state unchanged. Treat the string as data: expressions with calls or executable statements must be rejected without executing them. The `ast` standard-library module, including its literal parsing API, is permitted by the import policy.

The log is an ordered sequence of strings; either a list or tuple output encoding is accepted. Preserve any entries already supplied to the monad. Correct the code to satisfy this value, logging, and isolation contract.
