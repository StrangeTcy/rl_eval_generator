# Functorial Dataset Transformation

Your task is to implement an augmentation function in `dataset.py` that behaves as a functor preserving rotation symmetry (invariance).

Mathematically, an augmentation pipeline is functorial if it preserves the algebraic structure of the symmetry group. For a model $M$ that is $90^\circ$ rotation-invariant, any augmentation $T$ (like vertical flips or rotations) must commute with the model's prediction space:
$$M(T(x)) \equiv M(x)$$

The starting implementation in `dataset.py` contains a naive shear and crop transformation that does not preserve $90^\circ$ rotations, causing major performance drop when the dataset is rotated. Fix the augmentation function in `dataset.py` using pure $90^\circ$ rotations so that the invariants of the model are preserved under composition.
