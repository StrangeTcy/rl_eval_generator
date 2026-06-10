# Compositional Optimizer Implementation

Your task is to implement/correct a Compositional Optimizer system in `optimizer.py` that respects monoid associativity.

In Category Theory, sequential operations (like composing gradient updates or scaling factors) can be modeled as endomorphisms forming a Monoid under composition. For composition to be associative:
$$((A \circ B) \circ C)(p) \equiv (A \circ (B \circ C))(p)$$

The starting implementation of `%%MODEL_CLASS%%` has a bug where individual optimizer modules mutate a shared global state dictionary in-place instead of keeping states isolated per parameter/module. This causes the composed updates to depend on the nesting parenthesis order (violating associativity).

Refactor the modules in `optimizer.py` to keep their internal momentum states isolated, ensuring true associative composition.
