"""Rotary position embedding implementation."""
import torch
import torch.nn as nn


class RotaryEmbedding(nn.Module):
    def __init__(self, dim: int, base: float = 10000.0):
        super().__init__()
        if dim % 2 != 0:
            raise ValueError("RoPE dimension must be even")
        self.dim = dim
        self.base = base
        %%FREQ_BUFFER%% = 1.0 / (base ** (torch.arange(0, dim, 2).float() / %%INV_FREQ_DENOM%%))
        self.register_buffer("%%FREQ_BUFFER%%", %%FREQ_BUFFER%%, persistent=False)

    def _angles(self, seq_len: int, device, offset: int = 0, positions=None):
        if positions is None:
            # BUG: cached decoding should use absolute positions offset..offset+T-1.
            positions = torch.arange(seq_len, device=device)
        else:
            positions = positions.to(device)
        %%ANGLE_VAR%% = torch.einsum("s,d->sd", positions.float(), self.%%FREQ_BUFFER%%.to(device))
        return %%ANGLE_VAR%%

    %%BUG_COMMENT%%
    def %%ROTATE_HELPER%%(self, x: torch.Tensor) -> torch.Tensor:
        half = x.shape[-1] // 2
        x1 = x[..., :half]
        x2 = x[..., half:]
        return torch.cat((-x2, x1), dim=-1)

    def apply_rope(self, x: torch.Tensor, positions=None, offset: int = 0) -> torch.Tensor:
        """Apply rotary position embeddings to x of shape (B, H, T, D)."""
        if x.shape[-1] != self.dim:
            raise ValueError(f"Expected last dimension {self.dim}, got {x.shape[-1]}")
        seq_len = x.shape[-2]
        angles = self._angles(seq_len, x.device, offset=offset, positions=positions)
        cos = torch.repeat_interleave(angles.cos(), repeats=2, dim=-1)
        sin = torch.repeat_interleave(angles.sin(), repeats=2, dim=-1)
        while cos.ndim < x.ndim:
            cos = cos.unsqueeze(0)
            sin = sin.unsqueeze(0)
        return (x * cos) + (self.%%ROTATE_HELPER%%(x) * sin)

    def forward(self, x: torch.Tensor, positions=None, offset: int = 0) -> torch.Tensor:
        return self.apply_rope(x, positions=positions, offset=offset)
