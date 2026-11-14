import torch
from dataset import %%MODEL_CLASS%%

def test_shape():
    augmenter = %%MODEL_CLASS%%()
    x = torch.randn(1, 3, 32, 32)
    out = augmenter.augment(x, quarter_turns=1)
    assert out.shape == x.shape
    assert torch.equal(out, torch.rot90(x, 1, (-2, -1)))
    assert torch.equal(augmenter.augment(out, 3), x)
