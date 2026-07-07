import re

class %%MODEL_CLASS%%:
    """
    State transition engine over string representations.
    """
    def __init__(self):
        pass

    def step(self, state_str: str) -> str:
        """
        Perform one synchronous step of the Rule 110 cellular automaton on `state_str`.
        Boundary cells outside index 0 and len(state_str)-1 are treated as '0'.
        """%%PERF_COMMENT%%
        # Buggy initial implementation: returns identity without computing state transition
        return state_str
