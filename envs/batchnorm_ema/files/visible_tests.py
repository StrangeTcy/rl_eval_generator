import torch
import pytest
import torch.nn as nn
from model import ResNetBN


def test_model_forward():
    out = ResNetBN()(torch.randn(2, 3, 32, 32))
    assert out.shape == (2, %%NUM_CLASSES%%)


def test_model_has_batchnorm():
    bns = [m for m in ResNetBN().modules() if isinstance(m, nn.BatchNorm2d)]
    assert len(bns) > 0


def test_output_finite():
    out = ResNetBN()(torch.randn(2, 3, 32, 32))
    assert torch.isfinite(out).all()


%%VISIBLE_BN_TEST%%