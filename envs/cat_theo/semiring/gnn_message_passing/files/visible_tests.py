import torch
from gnn import %%MODEL_CLASS%%

def test_shape():
    layer = %%MODEL_CLASS%%(in_features=8, out_features=8)
    adj = torch.eye(4)
    x = torch.randn(4, 8)
    out = layer(adj, x)
    assert out.shape == x.shape
