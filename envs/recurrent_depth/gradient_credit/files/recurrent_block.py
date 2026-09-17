import torch
from torch import nn


class CreditBlock(nn.Module):
    def __init__(self, input_dim=4, hidden_dim=4, depth=%%TRAIN_DEPTH%%):
        super().__init__()
        self.transition = nn.Linear(input_dim, hidden_dim)
        self.depth = int(depth)
        %%IMPLEMENTATION_NOTE%%

    def forward(self, x: torch.Tensor, depth=None) -> torch.Tensor:
        steps = self.depth if depth is None else int(depth)
        state = x
        for _ in range(max(0, steps)):
            # BUG: detaching here destroys recurrent credit assignment.
            state = self.transition(state).detach()
        return state
