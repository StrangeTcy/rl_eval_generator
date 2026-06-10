import torch

def shift_2d(x: torch.Tensor, shift_h: int = 1, shift_w: int = 1) -> torch.Tensor:
    """Cyclic shifts across spatial dimensions (height and width)."""
    return torch.roll(x, shifts=(shift_h, shift_w), dims=(2, 3))
