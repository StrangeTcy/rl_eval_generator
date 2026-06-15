import torch
from semirings import %%ARITH_CLASS%%
from matrix_ops import generic_matmul

def test_arithmetic_matmul():
    A = [[1.0, 2.0], [3.0, 4.0]]
    B = [[5.0, 6.0], [7.0, 8.0]]
    out = generic_matmul(A, B, %%ARITH_CLASS%%)
    assert out[0][0] == 19.0
    assert out[1][1] == 50.0
