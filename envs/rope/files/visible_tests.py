import torch
from rope import RotaryEmbedding
from model import TinyRoPEModel
from cache import PositionCache


def test_rope_preserves_shape():
    rope = RotaryEmbedding(dim=8)
    x = torch.randn(2, 3, 7, 8)
    assert rope.apply_rope(x).shape == x.shape


def test_short_context_equivalence():
    # Public diagnostics check observable invariants of a rotary transform.
    torch.manual_seed(0)
    rope = RotaryEmbedding(dim=%%SHORT_TEST_DIM%%)
    x = torch.randn(1, 1, 4, %%SHORT_TEST_DIM%%)
    actual = rope.apply_rope(x)
    assert torch.allclose(actual.norm(dim=-1), x.norm(dim=-1), atol=1e-5, rtol=1e-5)
    assert torch.allclose(actual[..., 0, :], x[..., 0, :], atol=1e-5, rtol=1e-5)


def test_chunked_shape_matches_full_shape():
    model = TinyRoPEModel(dim=8, heads=2)
    x = torch.randn(2, 13, 8)
    q_full, k_full = model.forward_full(x)
    q_chunk, k_chunk = model.forward_chunked(x, chunk_size=5)
    assert q_full.shape == q_chunk.shape
    assert k_full.shape == k_chunk.shape


def test_cache_object_smoke():
    cache = PositionCache()
    assert isinstance(cache.position_offset(), int)
    cache.append(3)


%%EXTRA_VISIBLE_TEST%%
