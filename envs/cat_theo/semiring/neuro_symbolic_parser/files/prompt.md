# Differentiable Parsing Step

Your task is to correct the transition minimization step in `parser.py`.

`smooth_min(x, y)` must compute the elementwise unnormalized log-sum-exp soft minimum at the positive constructor temperature, retaining the input shape, dtype, device, and gradients. Its absolute value is part of the contract; adding a constant or applying a mean-normalization term is incorrect.

Implement a numerically stable formulation for finite floating-point inputs, including ties and large positive or negative values. The judge compares values and derivatives at multiple positive temperatures with tolerance `%%TOLERANCE%%`.
