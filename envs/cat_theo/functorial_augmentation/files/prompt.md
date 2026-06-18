# Symmetry Preserving Augmentations

Your task is to correct the dataset augmentation pipeline `%%MODEL_CLASS%%` in `dataset.py`.

For downstream layers that rely on specific geometric invariants (such as $90^\circ$ rotational invariance), any augmentation function $T$ must act as a functor preserving these structural symmetries. If $T$ introduces distortions or shears that violate the group orbit of the symmetry, accuracy degrades under transformation.

The current implementation in `dataset.py` runs, but fails to preserve the required geometric symmetries. Correct the augmentation function to ensure it preserves these structural invariants under composition.
