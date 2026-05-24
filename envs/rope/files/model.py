"""Tiny module wiring RoPE, an attention wrapper, and a position cache."""
import torch
import torch.nn as nn

from attention import RotaryFeatureProjector
from cache import PositionCache


class TinyRoPEModel(nn.Module):
    def __init__(self, dim: int = 8, heads: int = 2):
        super().__init__()
        self.projector = RotaryFeatureProjector(dim=dim, heads=heads)

    def forward_full(self, x: torch.Tensor):
        return self.projector.apply_full(x)

    def forward_chunked(self, x: torch.Tensor, chunk_size: int = 5):
        cache = PositionCache()
        qs, ks = [], []
        for start in range(0, x.shape[1], chunk_size):
            q, k = self.projector.apply_chunk(x[:, start:start + chunk_size], cache)
            qs.append(q)
            ks.append(k)
        return torch.cat(qs, dim=2), torch.cat(ks, dim=2)


# Backward-compatible alias for local scripts that only need the RoPE class.
from rope import RotaryEmbedding  # noqa: E402,F401
