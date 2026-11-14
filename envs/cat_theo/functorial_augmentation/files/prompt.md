# Symmetry Preserving Augmentations

Your task is to correct the dataset augmentation pipeline `%%MODEL_CLASS%%` in `dataset.py`.

Implement the deterministic C4 action `augment(x, quarter_turns=0)`: rotate the last two tensor dimensions counterclockwise by `quarter_turns * 90` degrees, interpreting the integer modulo four. A call without the second argument is the identity action. Preserve dtype, device, batch, and channel dimensions; a quarter turn exchanges rectangular height and width. Reflections, interpolation, cropping, and random sampling are outside this contract.

Composition must satisfy `augment(augment(x, a), b) = augment(x, a + b)`. The judge directly checks all four rotations and composition. The selected rectangular-width increment is `%%AUG_PARAM%%`.
