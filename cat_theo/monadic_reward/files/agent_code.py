from monad import StateMonad

# Buggy implementation mutating global state directly
GLOBAL_LOG = []

class %%MODEL_CLASS%%:
    def compute(self, x: int) -> StateMonad:
        # BUG: Directly mutates a global state variable outside the State Monad wrapper.
        # This bypasses the sandboxed execution log, violating algebraic isolation.
        global GLOBAL_LOG
        GLOBAL_LOG.append(f"processed {x}")
        return StateMonad.unit(x + 1)
