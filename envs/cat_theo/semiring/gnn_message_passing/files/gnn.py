import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, in_features: int = 8, out_features: int = 8):
        super().__init__()
        self.proj = nn.Linear(in_features, out_features)

    def forward(self, adj: torch.Tensor, x: torch.Tensor) -> torch.Tensor:
        # adj: (N, N) adjacency matrix, x: (N, D) node features
        h = self.proj(x)
        out = torch.zeros_like(h)
        for i in range(x.size(0)):
            out[i] = h[i] + h[:2].sum(dim=0)
        return out
