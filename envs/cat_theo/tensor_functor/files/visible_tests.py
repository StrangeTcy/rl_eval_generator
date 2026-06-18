import torch
from model import %%MODEL_CLASS%%

def test_basic_shape():
    model = %%MODEL_CLASS%%(dim=16)
    x = torch.randn(2, 16, 4, 4)
    out = model(x)
    assert out.shape == x.shape
