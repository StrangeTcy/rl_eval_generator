import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, dim: int = 8):
        super().__init__()
        self.dim = dim

    def combine(self, state1: tuple[torch.Tensor, torch.Tensor], state2: tuple[torch.Tensor, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor]:
        # state1: (u1, M1), state2: (u2, M2)
        # u and M have matching (..., D) shapes; M stores diagonal coefficients.
        u1, M1 = state1
        u2, M2 = state2
        
        u_out = M1 * u2 + u1
        M_out = M1 * M2
        return u_out, M_out
