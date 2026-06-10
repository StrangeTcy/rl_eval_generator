# Adjunction Between Tokenizers and Detokenizers

Your task is to implement a robust Detokenizer in `detokenizer.py` that forms a correct Galois connection (adjunction) with the tokenizer in `tokenizer.py`.

In Category Theory, a lossy tokenizer and its corresponding detokenizer form an adjunction. Let $T: S \to K$ be the tokenizer, and $D: K \to S$ be the detokenizer. For them to form a valid adjunction, they must satisfy:
1. **Unit Property:** $T \circ D \circ T(s) \equiv T(s)$
2. **Adjunction Invariant:** For any string $s$ and token list $t$, detokenize-then-tokenize must be idempotent on token streams.

The starting implementation in `detokenizer.py` uses a naive string join, which fails on word boundaries (whitespace merging) and emoji byte sequences. Correct the detokenizer so that it preserves structural unicode word boundaries and behaves as a mathematically correct adjoint.
