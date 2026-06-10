# The Monadic Reward Verifier

Your task is to implement a correct monadic state transition function in `agent_code.py` using the State Monad defined in `monad.py`.

In sandboxed execution, we want to isolate code side-effects (such as unauthorized filesystem access or global state mutation) from the reward verifier. We model state transitions as a State Monad:
$$S \to (A, S)$$
where $S$ is the log of allowed operations, and $A$ is the computation result.

The starting implementation in `agent_code.py` bypasses the monad wrapper by mutating global variables or printing results directly, which violates the algebraic state encapsulation of the monad. Correct the code to use the monad `bind` and `return` operations properly so that all state transitions are logged.
