# Exact Tokenization Round Trip

Implement `%%MODEL_CLASS%%.detokenize` in `detokenizer.py` as an inverse of the supplied tokenizer on its supported domain.

The supported domain is every Unicode string that does not contain the literal reserved character `Ġ` (U+0120). That character is a token marker, not a supported source-text character. Spaces, repeated spaces, tabs, line breaks, combining characters, and emoji must otherwise be preserved exactly. Only token sequences emitted by `tokenize` on this domain are supplied to the detokenizer.

For every supported string `s`, require `D(T(s)) == s` and consequently `T(D(T(s))) == T(s)`. These are reconstruction and token round-trip contracts; they do not by themselves establish a categorical adjunction or Galois connection.
