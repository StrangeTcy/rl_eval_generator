# Token Reconstruction and Normalization

Implement `%%MODEL_CLASS%%` in `detokenizer.py` to reconstruct strings encoded by the fixed tokenizer in `tokenizer.py`.

Let $T$ be the tokenizer and $D$ the detokenizer. Require exact reconstruction `D(T(s)) = s` and normalization stability:
$$T \circ D \circ T(s) \equiv T(s)$$
for every supported input string $s$.

The supported domain excludes the literal character `Ġ` (U+0120), which is reserved as the tokenizer's space marker; the tokenizer rejects it. All other Unicode characters, repeated spaces, tabs, and empty strings are supported. These are reconstruction laws, without a claim of a categorical adjunction or Galois connection.
