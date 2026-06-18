# Monadic Verification & Sandboxing

Your task is to correct the state transition logic `%%MODEL_CLASS%%` in `agent_code.py` using the State Monad defined in `monad.py`.

In verifiable reward harnesses, we want to isolate code execution from external environmental side-effects. We model state transitions purely as a State Monad:
$$S \to (A, S)$$
where $S$ is the log of allowed transitions, and $A$ is the computation output.

The current implementation in `agent_code.py` runs, but violates the strict algebraic state encapsulation of the monad by triggering forbidden side-effects. Correct the code to use the State Monad correctly so that all state updates are securely encapsulated.
