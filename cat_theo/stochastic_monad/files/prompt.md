# Monad-Correct Stochastic Computation

Your task is to implement/correct a Probability Monad in `monad.py` that strictly obeys the standard monad laws.

In functional programming and Category Theory, stochastic computations can be modeled as monads (Kleisli arrows). For the monad to compose correctly, it must satisfy:
1. **Left Identity:** `return x >>= f == f x`
2. **Right Identity:** `m >>= return == m`
3. **Associativity:** `(m >>= f) >>= g == m >>= (\x. f(x) >>= g)`

The starting implementation of `%%MODEL_CLASS%%` has a buggy `bind` method that mutates shared state, breaking the Associativity law. Refactor the `bind` and `unit` (return) operations so that they behave functionally and pass all the monad laws.
