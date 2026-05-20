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


%%VISIBLE_TEST_BODY%%