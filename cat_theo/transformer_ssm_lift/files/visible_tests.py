import torch
from lifter import %%MODEL_CLASS%%

def test_shape():
    lifter = %%MODEL_CLASS%%(dim=8)
    K = torch.randn(2, 4, 8)
    V = torch.randn(2, 4, 8)
    out = lifter.lift_state(K, V)
    assert out.shape == (2, 8, 8)
