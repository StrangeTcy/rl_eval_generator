# Functor-Correct Tensor Operation Refactoring

Your task is to refactor a rigid, non-compositional spatial-channel mixing layer into a functor-correct form that is coordinate-free.

The original implementation in `model.py` uses rigid dimensions and loops. This works for standard batch sizes, but violates the mathematical properties of a tensor functor:
1. It does not behave naturally under batching (meaning applying the function to a batched tensor via `torch.vmap` produces shape/indexing errors).
2. It breaks under coordinate resizing (due to hardcoded dimension slicing under hard difficulty, representing a coordinate-trap).

To solve this, refactor `%%MODEL_CLASS%%` in `model.py` such that:
- It uses coordinate-free operators like `einops` for shape manipulation.
- It is fully compatible with the vectorization functor (`torch.vmap`) and automatic differentiation (`torch.func`).
- Any coordinate-trap slices like `x[:, :, :self.size, :self.size]` are replaced with safe, dynamically shaped operations.

Run the visible tests using `pytest` to make sure your basic implementation runs correctly.
