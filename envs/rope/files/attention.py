"""Tiny attention-adjacent wrapper that applies RoPE to projected features."""
import torch
import torch.nn as nn

from rope import RotaryEmbedding
from cache import PositionCache


class RotaryFeatureProjector(nn.Module):
    def __init__(self, dim: int = 8, heads: int = 2):
        super().__init__()
        self.heads = heads
        self.head_dim = dim
        self.q_proj = nn.Linear(dim, heads * dim)
        self.k_proj = nn.Linear(dim, heads * dim)
        self.rope = RotaryEmbedding(dim)

    def _project(self, x: torch.Tensor):
        b, t, _ = x.shape
        q = self.q_proj(x).view(b, t, self.heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(b, t, self.heads, self.head_dim).transpose(1, 2)
        return q, k

    def apply_full(self, x: torch.Tensor):
        q, k = self._project(x)
        return self.rope(q, offset=0), self.rope(k, offset=0)

    def apply_chunk(self, x: torch.Tensor, cache: PositionCache):
        q, k = self._project(x)
        # BUG: this should use the cache's current absolute position offset.
        offset = 0
        q = self.rope(q, offset=offset)
        k = self.rope(k, offset=offset)
        cache.append(x.shape[1])
        return q, k
