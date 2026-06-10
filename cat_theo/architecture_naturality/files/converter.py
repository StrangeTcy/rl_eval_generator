import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, dim: int = 16):
        super().__init__()
        # The natural transformation should scale the hidden state uniformly.
        # BUG: Hardcoded sequence length slice, which violates naturality under temporal slicing.
        self.scale = nn.Parameter(torch.tensor(2.0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.scale * x[:, :8, :]
