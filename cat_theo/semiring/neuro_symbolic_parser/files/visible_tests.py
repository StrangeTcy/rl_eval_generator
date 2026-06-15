import torch
from parser import %%MODEL_CLASS%%

def test_shape():
    parser = %%MODEL_CLASS%%()
    x = torch.tensor([1.0], requires_grad=True)
    y = torch.tensor([2.0], requires_grad=True)
    out = parser.smooth_min(x, y)
    assert out.shape == x.shape
