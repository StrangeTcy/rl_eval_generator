import torch
from dataset import %%MODEL_CLASS%%

def test_shape():
    augmenter = %%MODEL_CLASS%%()
    x = torch.randn(1, 3, 32, 32)
    out = augmenter.augment(x)
    assert out.shape == x.shape
