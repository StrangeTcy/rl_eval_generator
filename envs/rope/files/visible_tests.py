import torch
from rope import RotaryEmbedding
from model import TinyRoPEModel
from cache import PositionCache


def test_rope_preserves_shape():
    rope = RotaryEmbedding(dim=8)
    x = torch.randn(2, 3, 7, 8)
    assert rope.apply_rope(x).shape == x.shape


def test_short_context_equivalence():
    # A finite example of the paper's transform; general cases are held out.
    torch.manual_seed(0)
    rope = RotaryEmbedding(dim=%%SHORT_TEST_DIM%%)
    x = torch.ones(1, 1, 4, %%SHORT_TEST_DIM%%)
    expected = torch.tensor((
        (1.0000000000, 1.0000000000, 1.0000000000, 1.0000000000),
        (-0.3011686789, 1.3817732907, 0.9899501671, 1.0099498338),
        (-1.3254442634, 0.4931505903, 0.9798013400, 1.0197986734),
        (-1.1311125047, -0.8488724885, 0.9695545335, 1.0295455340),
    ))[:, :%%SHORT_TEST_DIM%%].reshape(1, 1, 4, %%SHORT_TEST_DIM%%)
    actual = rope.apply_rope(x)
    assert torch.allclose(actual, expected, atol=1e-5, rtol=1e-5)


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
