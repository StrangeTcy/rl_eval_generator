# Monadic Verification & Sandboxing

Your task is to correct the state transition logic `%%MODEL_CLASS%%` in `agent_code.py` using the State Monad defined in `monad.py`.

In verifiable reward harnesses, we want to isolate code execution from external environmental side-effects. We model state transitions purely as a State Monad:
$$S \to (A, S)$$
where $S$ is the log of allowed transitions, and $A$ is the computation output.

`compute(x)` accepts a serialized pair of numeric coordinates and returns a State Monad whose value is the first coordinate plus one. Running it appends `processed <first coordinate>` to the supplied log, without mutating that input log or module state. Constructing the monad must have no external effects. Reject executable expressions: parse data as literals only. The `ast` module and `ast.literal_eval` are permitted by the import policy.

Legacy control label: `%%SIDE_EFFECT_CHECK%%`. This is presentation metadata only; all state-isolation and literal-parsing checks always run.
