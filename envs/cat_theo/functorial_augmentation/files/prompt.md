# Symmetry Preserving Augmentations

Your task is to correct the dataset augmentation pipeline `%%MODEL_CLASS%%` in `dataset.py`.

Implement the C4 rotation action `augment(x, quarter_turns=0)` on the final two tensor dimensions. The caller supplies `quarter_turns` as 0, 1, 2, or 3; return the corresponding counterclockwise rotation by that many multiples of 90 degrees. Preserve all values, channels, batch dimensions, dtype, and device. Odd quarter turns exchange height and width on rectangular inputs. Reflections, interpolation, cropping, and additional random transformations are outside the allowed action.

The judge supplies all four group elements directly and checks composition. There is no random sampling quota: randomness may choose a group element upstream, but this method must apply the requested element deterministically. Calling the method without the optional argument requests the identity element.
