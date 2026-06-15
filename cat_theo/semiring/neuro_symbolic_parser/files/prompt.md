# Differentiable Parsing Step

Your task is to correct the transition minimization step in `parser.py`.

To allow backpropagation of gradients through dynamic programming layers, hard minimum operations must be replaced with a smooth, differentiable minimum. 

The current implementation of `smooth_min` in `parser.py` is non-differentiable, causing gradients to be zeroed out. Correct the function using a smooth Log-Sum-Exp (LSE) formulation so that non-trivial gradients flow perfectly back to the input parameters.
