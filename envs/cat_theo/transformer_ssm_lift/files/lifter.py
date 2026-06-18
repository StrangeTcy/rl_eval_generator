import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, dim: int = 8):
        super().__init__()
        self.dim = dim

    def lift_state(self, K: torch.Tensor, V: torch.Tensor) -> torch.Tensor:
        # BUG: Naive temporal mean pooling.
        # This collapses the associative sequence context into a simple diagonal vector,
        # losing historical temporal correlations.
        B, T, D = K.shape
        out = torch.zeros(B, D, D, device=K.device)
        for b in range(B):
            m_v = V[b].mean(dim=0)
            out[b] = torch.diag(m_v)
        return out
