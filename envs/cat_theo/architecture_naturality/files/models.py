import torch
import torch.nn as nn

class TransformerFunctor(nn.Module):
    def __init__(self, dim: int = 16):
        super().__init__()
        self.dim = dim
        # Linear layer with fixed weights for testing
        self.proj = nn.Linear(dim, dim, bias=False)
        with torch.no_grad():
            self.proj.weight.fill_(1.0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x)

class RNNFunctor(nn.Module):
    def __init__(self, dim: int = 16):
        super().__init__()
        self.dim = dim
        self.proj = nn.Linear(dim, dim, bias=False)
        with torch.no_grad():
            self.proj.weight.fill_(2.0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x)
