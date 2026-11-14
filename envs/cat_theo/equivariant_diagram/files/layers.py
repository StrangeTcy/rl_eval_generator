import torch
import torch.nn as nn

class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, in_channels: int = 16, out_channels: int = 16):
        super().__init__()
        self.proj = nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x)
