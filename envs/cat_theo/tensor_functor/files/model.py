import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, dim: int = 16):
        super().__init__()
        self.dim = dim
        self.proj = nn.Linear(dim, dim)
        %%DIM_CHECK%%

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # BUG: Rigid looping and coordinate traps that violate functorial properties.
        # This code works only for a fixed coordinate size and breaks under vmap and resizing.
        
        x_sliced = %%RIGID_SLICE%%
        
        b, c, h, w = x_sliced.shape
        out = torch.zeros_like(x_sliced)
        for i in range(h):
            for j in range(w):
                # Rigid linear projection along channel dimension
                out[:, :, i, j] = self.proj(x_sliced[:, :, i, j])
                
        return out
