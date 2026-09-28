import torch
from torch import nn


class RecurrentBlock(nn.Module):
    """A small weight-tied transition block."""

    def __init__(self, input_dim=4, hidden_dim=4, depth=%%TRAIN_DEPTH%%):
        super().__init__()
        self.transition = nn.Linear(input_dim, hidden_dim)
        self.depth = int(depth)
        %%IMPLEMENTATION_NOTE%%

    def forward(self, x: torch.Tensor, depth=None) -> torch.Tensor:
        steps = self.depth if depth is None else int(depth)
        state = x
        for _ in range(max(0, steps)):
            # BUG: this ignores the state produced by the preceding transition.
            state = self.transition(x)
        return state
