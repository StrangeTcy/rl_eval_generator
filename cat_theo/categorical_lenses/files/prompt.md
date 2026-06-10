# Bidirectional Lenses in Data Pipelines

Your task is to implement/correct a Bidirectional Lens `%%MODEL_CLASS%%` in `lenses.py`.

In categorical cybernetics, a Lens is a bidirectional transformation consisting of two functions:
- `view(s)`: extracts or projects a feature $A$ from a state $S$.
- `update(s, a)`: updates or puts a modified feature $A$ back into the state $S$.

For a Lens to be valid, it must strictly satisfy the three fundamental Lens Laws:
1. **Put-Get (Retention):** `view(update(s, a)) == a`
2. **Get-Put (Identity):** `update(s, view(s)) == s`
3. **Put-Put (Composition):** `update(update(s, a), a') == update(s, a')`

The starting implementation in `lenses.py` contains a naive update function that leaks state or fails to preserve un-updated coordinates, violating the lens laws. Correct the implementation to satisfy all three algebraic equations.
