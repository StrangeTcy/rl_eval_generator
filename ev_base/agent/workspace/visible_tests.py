import torch
import pytest
from dataset import ShapesDataset


def test_dataset_contrastive():
    q, k, y = ShapesDataset(8, contrastive=True)[0]
    assert q.shape == (1, 16, 16)
    assert k.shape == (1, 16, 16)
    assert y.item() in range(4)


def test_dataset_linear():
    x, y = ShapesDataset(8, contrastive=False)[0]
    assert x.shape == (1, 16, 16)


def test_temperature_not_cancelled():
    """Low tau must produce larger logits than high tau."""
    import importlib
    mod   = importlib.import_module("moco_model")
    Model = getattr(mod, "MoCo")
    torch.manual_seed(0)
    m_warm = Model(dim=16, K=64, tau=1.0)
    m_cold = Model(dim=16, K=64, tau=0.01)
    m_cold.load_state_dict(m_warm.state_dict(), strict=False)
    m_cold.tau = 0.01
    im = torch.randn(4, 1, 16, 16)
    with torch.no_grad():
        lw, _ = m_warm(im, im)
        lc, _ = m_cold(im, im)
    assert lc.abs().max() > lw.abs().max() * 5
