# Compositional Pipeline Invariants

Your task is to implement a robust, globally consistent preprocessing pipeline wrapper in `pipeline.py`.

In deep learning data pipelines, multiple sequential modules are chained together (e.g. `Normalizer -> Discretizer -> Tokenizer`). While each module maintains its own local mathematical constraints and boundaries in isolation, combining them sequentially can cause boundary leaks under extreme out-of-distribution inputs.

The task is to complete the `%%MODEL_CLASS%%` class in `pipeline.py` such that:
1. It successfully chains the normalizer and discretizer modules together.
2. It is robust under large adversarial float values, preventing coordinate overflow or boundary leaks that crash downstream modules.

The current implementation in `pipeline.py` works on standard inputs but crashes on extreme out-of-distribution coordinates. Correct the implementation to guarantee global boundary safety.
