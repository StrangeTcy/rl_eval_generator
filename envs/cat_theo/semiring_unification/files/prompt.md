# Semiring Unification (Algebraic Symmetries)

Your task is to implement three complete Semirings in `semirings.py`:
1. `%%ARITH_CLASS%%`: Standard real-number addition and multiplication.
2. `%%TROP_CLASS%%`: The Min-Plus (Tropical) semiring, where the additive operation $\oplus$ is `min`, and the multiplicative operation $\otimes$ is standard addition `+`.
3. `%%BOOL_CLASS%%`: The Boolean semiring, where the additive operation $\oplus$ is logical `or`, and the multiplicative operation $\otimes$ is logical `and`.

### Semiring Definition
A Semiring is a set equipped with two binary operations, addition ($\oplus$) and multiplication ($\otimes$), satisfying the following laws:
1. **Additive Identity:** There exists a `zero` element such that `oplus(x, zero) == x`.
2. **Multiplicative Identity:** There exists a `one` element such that `otimes(x, one) == x`.
3. **Multiplicative Annihilation:** `otimes(x, zero) == zero`.
4. **Distributivity:** Multiplication distributes over addition:
   `otimes(x, oplus(y, z)) == oplus(otimes(x, y), otimes(x, z))`

### The Bug
The starting code in `semirings.py` contains incorrect `zero` and `one` identity elements and wrong operator implementations (for example, using standard multiplication instead of addition for the tropical multiplicative step, or standard zero instead of infinity for the tropical additive identity).

Correct these classes so that they satisfy all semiring laws. The judge will evaluate your score based on which algebraic laws pass.
