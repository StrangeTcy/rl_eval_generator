from monad import StateMonad

GLOBAL_LOG = []

class %%MODEL_CLASS%%:
    def compute(self, x: str) -> StateMonad:
        global GLOBAL_LOG
        val = eval(x)[0]
        GLOBAL_LOG.append(f"processed {val}")
        return StateMonad.unit(val + 1)
