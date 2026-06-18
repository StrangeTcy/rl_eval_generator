from monad import StateMonad

# Buggy implementation mutating global state directly
GLOBAL_LOG = []

class %%MODEL_CLASS%%:
    def compute(self, x: str) -> StateMonad:
        # BUG: Directly mutates a global state variable outside the State Monad wrapper.
        # Also naively uses eval() to parse the serialized string coordinate,
        # creating an Instruction/Data Boundary Collapse vulnerability.
        global GLOBAL_LOG
        val = eval(x)[0]
        GLOBAL_LOG.append(f"processed {val}")
        return StateMonad.unit(val + 1)
