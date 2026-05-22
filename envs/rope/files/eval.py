"""Local smoke evaluation for the RoPE environment."""
import torch
from model import RotaryEmbedding


def main():
    rope = RotaryEmbedding(dim=8)
    x = torch.randn(2, 3, 16, 8)
    y = rope.apply_rope(x)
    print(f"input shape:  {tuple(x.shape)}")
    print(f"output shape: {tuple(y.shape)}")
    print(f"norm delta:   {(x.norm(dim=-1) - y.norm(dim=-1)).abs().max().item():.6f}")


if __name__ == "__main__":
    main()
