# Stateful Attention-to-Recurrence Lift

Your task is to correct the state lifting function `%%MODEL_CLASS%%` in `lifter.py`.

For batched keys `K` and values `V` of shape `(B, T, D)`, return a state of shape `(B, D, D)`. For any query `q`, the readout `q @ state` must equal `(q @ K.transpose(-1, -2)) @ V`. States for concatenated histories must equal the sum of their states.

Preserve this unnormalized linear-attention readout exactly within floating-point tolerance. The contract does not include softmax normalization or recovery of the original sequence history from the state.
