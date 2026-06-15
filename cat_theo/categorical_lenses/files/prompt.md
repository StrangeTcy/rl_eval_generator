# Bidirectional Lens Laws

Your task is to correct the bidirectional state transformation `%%MODEL_CLASS%%` in `lenses.py`.

A Lens is a bidirectional mapping consisting of two functions:
- `view(s)`: projects a feature from a state $S$.
- `update(s, a)`: updates or puts a modified feature back into the state $S$.

To be a mathematically valid Lens, it must strictly satisfy the three fundamental Lens Laws under composition:
1. **Put-Get (Retention):** `view(update(s, a)) == a`
2. **Get-Put (Identity):** `update(s, view(s)) == s`
3. **Put-Put (Composition):** `update(update(s, a), a') == update(s, a')`

The current implementation in `lenses.py` runs, but fails these laws. Correct the implementation to satisfy all three algebraic equations.
