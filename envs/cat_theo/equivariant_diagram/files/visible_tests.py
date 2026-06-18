import torch
from layers import %%MODEL_CLASS%%
from symmetry import shift_2d

def test_shape():
    layer = %%MODEL_CLASS%%()
    x = torch.randn(2, 16, 8, 8)
    out = layer(x)
    assert out.shape == x.shape
