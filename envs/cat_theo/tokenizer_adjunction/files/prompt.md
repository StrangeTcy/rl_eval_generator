# Adjoint Tokenization & Detokenization

Your task is to implement a robust Detokenizer in `detokenizer.py` that forms a mathematically correct adjunction (Galois connection) with the tokenizer in `tokenizer.py`.

Let $T$ be the tokenizer, and $D$ be the detokenizer. To form a valid adjunction, they must satisfy the algebraic unit property:
$$T \circ D \circ T(s) \equiv T(s)$$
for any input string $s$.

The starting implementation of `%%MODEL_CLASS%%` in `detokenizer.py` runs, but fails this adjunction property on complex boundary inputs. Correct the detokenization logic to ensure it behaves as a mathematically valid adjoint.
