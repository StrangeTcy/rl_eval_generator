import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, temperature: float = 1.0):
        super().__init__()
        self.temp = temperature

    def smooth_min(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        return torch.minimum(x, y).detach()
