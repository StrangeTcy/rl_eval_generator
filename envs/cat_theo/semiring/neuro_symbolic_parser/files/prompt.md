# Differentiable Parsing Step

Your task is to correct the transition minimization step in `parser.py`.

To allow backpropagation of gradients through dynamic programming layers, hard minimum operations must be replaced with a smooth, differentiable minimum. 

Implement `smooth_min(x, y) = -temperature * log(exp(-x / temperature) + exp(-y / temperature))` for positive temperature, preserving broadcasting and gradients. Compute this stably for tied inputs and large magnitudes. The judge compares both values and derivatives using tolerance `%%TOLERANCE%%` across several temperatures.
