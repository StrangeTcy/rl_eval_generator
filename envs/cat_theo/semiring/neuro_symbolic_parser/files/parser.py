import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, temperature: float = 1.0):
        super().__init__()
        self.temp = temperature

    def smooth_min(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        # BUG: Naive hard minimum with detachment.
        # This breaks gradient flow (producing zero gradients) back to the parameter inputs.
        # Replace this with the smooth Log-Sum-Exp semiring addition operator:
        # -temp * log( exp(-x/temp) + exp(-y/temp) )
        return torch.minimum(x, y).detach()
