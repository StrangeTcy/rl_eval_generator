# Commutative Equivariant Layer

Your task is to correct the layer `%%MODEL_CLASS%%` in `layers.py`.

A layer is strictly equivariant if its operation commutes with specified geometric group actions (symmetries) $g$ and $g'$:
$$(g' \circ f)(x) \equiv (f \circ g)(x)$$
for any input $x$ and any group action $g$ defined in `symmetry.py`.

The starting code in `layers.py` runs, but violates this commutative property. Correct the implementation so that it behaves equivariantly for any arbitrary transformation $g$ defined in `symmetry.py`.
