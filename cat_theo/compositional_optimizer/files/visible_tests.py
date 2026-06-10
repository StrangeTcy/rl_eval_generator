import torch
from optimizer import MomentumStep

def test_single_step():
    opt = MomentumStep(beta=0.9)
    p = torch.randn(2, 2)
    g = torch.randn(2, 2)
    out = opt.update(p, g)
    assert out.shape == p.shape
