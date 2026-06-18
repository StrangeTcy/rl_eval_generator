import torch

class %%MODEL_CLASS%%:
    def __init__(self, sample_fn):
        self.sample_fn = sample_fn

    @classmethod
    def unit(cls, x):
        """Monadic unit (return)."""
        return cls(lambda: x)

    def bind(self, f):
        """Monadic bind (>>=)."""
        # BUG: Evaluates self.sample_fn() immediately instead of lazily.
        # This collapses the dynamic distribution into a static point value at bind-time.
        val = self.sample_fn()
        return %%MODEL_CLASS%%(lambda: f(val).sample_fn())
