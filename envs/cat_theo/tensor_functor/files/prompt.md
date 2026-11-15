# Vectorized Dimension Mixer

Ensure that the channel-mixing layer `%%MODEL_CLASS%%` in `model.py` satisfies the following behavioral contract.

Inputs have shape `(B, C, H, W)` with `C` equal to the configured projection dimension. Apply the existing learned `self.proj` independently to the channel vector at each spatial position, preserving the batch and spatial dimensions. Support different positive `B`, `H`, and `W`, vectorization through `torch.vmap`, and gradients through the inputs and projection.

Some configured starters already satisfy this contract. Preserve compliant behavior and make semantic changes only when needed. The judge scores behavior and does not require an edit merely to satisfy a file-touch condition.
