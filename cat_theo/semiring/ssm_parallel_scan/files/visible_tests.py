import torch
from ssm import %%MODEL_CLASS%%

def test_combine_shapes():
    scanner = %%MODEL_CLASS%%()
    u1 = torch.randn(2, 8)
    M1 = torch.randn(2, 8)
    u2 = torch.randn(2, 8)
    M2 = torch.randn(2, 8)
    u_out, M_out = scanner.combine((u1, M1), (u2, M2))
    assert u_out.shape == u1.shape
    assert M_out.shape == M1.shape
