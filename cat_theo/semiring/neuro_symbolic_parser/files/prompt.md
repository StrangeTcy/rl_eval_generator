# Differentiable Viterbi/Dijkstra via Log-Sum-Exp Semiring

Your task is to implement a differentiable parsing step in `parser.py` using the Log-Sum-Exp semiring.

In neuro-symbolic AI, combining hard symbolic logic (such as sequence parsing or path-planning) with backpropagation requires **differentiable dynamic programming**. We do this by swapping:
- The **Tropical semiring** ($\min, +$) for finding exact shortest paths.
- The **Log-Sum-Exp (LSE) semiring** ($\text{logsumexp}, +$) for a smooth, fully differentiable approximation.

The starting implementation in `parser.py` uses a hard `min` or non-differentiable indexing step that breaks gradient flow (producing zero gradients). Implement the smooth `logsumexp` multiplication/addition step so that gradients can flow perfectly back to the neural parameter inputs.
