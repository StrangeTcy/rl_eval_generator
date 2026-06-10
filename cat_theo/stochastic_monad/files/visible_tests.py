import torch
from monad import %%MODEL_CLASS%%

def test_unit():
    m = %%MODEL_CLASS%%.unit(42)
    assert m.sample_fn() == 42
