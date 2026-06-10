import torch
from converter import %%MODEL_CLASS%%

def test_shape():
    tfm = %%MODEL_CLASS%%()
    x = torch.randn(2, 8, 16)
    out = tfm(x)
    assert out.shape == x.shape
