import torch
from torch import nn


class AdaptiveHaltingBlock(nn.Module):
    def __init__(self, input_dim=4, hidden_dim=4):
        super().__init__()
        self.transition = nn.Linear(input_dim, hidden_dim)
        %%IMPLEMENTATION_NOTE%%

    def forward(self, x: torch.Tensor, halt_after: torch.Tensor, max_steps=None) -> torch.Tensor:
        counts = torch.as_tensor(halt_after, device=x.device, dtype=torch.long)
        limit = int(counts.max().item()) if counts.numel() else 0
        if max_steps is not None:
            limit = min(limit, int(max_steps))
        state = x
        for step in range(limit):
            # BUG: every row runs for the batch maximum instead of its own count.
            state = self.transition(state)
        return state
