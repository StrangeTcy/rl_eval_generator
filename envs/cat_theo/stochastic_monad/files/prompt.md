# Correct Composition of Stochastic Mappers

Your task is to correct the monadic class `%%MODEL_CLASS%%` in `monad.py`.

To allow sequential stochastic computations to compose correctly, the monadic class must satisfy the standard algebraic monad laws:
1. **Left Identity:** `return x >>= f == f x`
2. **Right Identity:** `m >>= return == m`
3. **Associativity:** `(m >>= f) >>= g == m >>= (\x. f(x) >>= g)`

The current implementation in `monad.py` runs, but fails these laws. Correct the `bind` and `unit` methods to ensure they compose functionally and satisfy all three laws under dynamic sampling.
