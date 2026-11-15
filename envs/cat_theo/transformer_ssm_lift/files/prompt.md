# Stateful Attention-to-Recurrence Lift

Your task is to correct the state lifting function `%%MODEL_CLASS%%` in `lifter.py`.

Inputs `K` and `V` have shape `(B, T, D)`. Return a state of shape `(B, D, D)` whose readout with any query tensor `Q` equals the unnormalized linear-attention readout `(Q @ K.transpose(-2, -1)) @ V`. Concatenating two histories must correspond to adding their lifted states.

Preserve this readout exactly up to numerical tolerance. The contract concerns unnormalized linear attention; it does not claim equivalence to softmax attention or invertibility of the complete sequence history.
