# Commutative Diagram Completion (Equivariant Network)

Your task is to implement an equivariant layer `%%MODEL_CLASS%%` in `layers.py`.

In deep learning, equivariance means the layer operations commute with group actions (such as spatial translation or channel shifts). Mathematically, this forms a commutative diagram:
```
           f
     X ──────────> Y
     │             │
     │ g           │ g'
     ▼             ▼
     X ──────────> Y
           f
```
where $f$ is your layer, and $g, g'$ are group actions (symmetries) defined in `symmetry.py`.

The starting code in `layers.py` implements a projection head that is not equivariant because it ignores spatial shift coordinate transitions. You must correct the layer $f$ such that $(g' \circ f)(x) \equiv (f \circ g)(x)$ for any input $x$ and any group action $g$ defined in `symmetry.py`.

Use the visible tests to verify the commutative property on basic inputs.
