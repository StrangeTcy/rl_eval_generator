import torch
import pytest
from dataset import GlyphDataset, NUM_CLASSES, IMG_SIZE, generate_glyph, CLASS_DEFS
from model import GlyphCNN


def test_dataset_output_shape():
    ds = GlyphDataset(num_samples=8, is_train=False)
    img, label = ds[0]
    assert img.shape == (1, IMG_SIZE, IMG_SIZE)
    assert img.dtype == torch.float32
    assert label.dtype == torch.long


def test_all_classes_representable():
    for class_id in range(NUM_CLASSES):
        assert generate_glyph(class_id) is not None


def test_class_defs_cover_all_classes():
    assert set(CLASS_DEFS.keys()) == set(range(NUM_CLASSES))


def test_model_forward_shape():
    model = GlyphCNN(num_classes=NUM_CLASSES)
    out   = model(torch.randn(4, 1, IMG_SIZE, IMG_SIZE))
    assert out.shape == (4, NUM_CLASSES)


def test_model_output_finite():
    model = GlyphCNN(num_classes=NUM_CLASSES)
    out   = model(torch.randn(4, 1, IMG_SIZE, IMG_SIZE))
    assert torch.isfinite(out).all()


%%EXTRA_TESTS%%