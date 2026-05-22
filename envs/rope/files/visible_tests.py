import torch
from model import RotaryEmbedding


def reference_rope_interleaved(x, positions=None, offset=0, base=10000.0):
    dim = x.shape[-1]
    if positions is None:
        positions = torch.arange(offset, offset + x.shape[-2], device=x.device)
    inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, device=x.device).float() / dim))
    angles = torch.einsum("s,d->sd", positions.float(), inv_freq)
    cos = angles.cos()
    sin = angles.sin()
    while cos.ndim < x.ndim - 1:
        cos = cos.unsqueeze(0)
        sin = sin.unsqueeze(0)
    even = x[..., 0::2]
    odd = x[..., 1::2]
    out = torch.empty_like(x)
    out[..., 0::2] = even * cos - odd * sin
    out[..., 1::2] = even * sin + odd * cos
    return out


def test_rope_preserves_shape():
    rope = RotaryEmbedding(dim=8)
    x = torch.randn(2, 3, 7, 8)
    assert rope.apply_rope(x).shape == x.shape


def test_short_context_equivalence():
    # At dim=2, adjacent-pair and half-split rotations coincide. This catches
    # gross shape/frequency errors without revealing the long-context bug.
    torch.manual_seed(0)
    rope = RotaryEmbedding(dim=%%SHORT_TEST_DIM%%)
    x = torch.randn(1, 1, 4, %%SHORT_TEST_DIM%%)
    expected = reference_rope_interleaved(x)
    actual = rope.apply_rope(x)
    assert torch.allclose(actual, expected, atol=1e-5, rtol=1e-5)


%%EXTRA_VISIBLE_TEST%%
