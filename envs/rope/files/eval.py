"""Local smoke evaluation for the RoPE cross-context environment."""
import torch
from model import TinyRoPEModel


def main():
    model = TinyRoPEModel(dim=8, heads=2)
    x = torch.randn(2, 17, 8)
    q_full, k_full = model.forward_full(x)
    q_chunk, k_chunk = model.forward_chunked(x, chunk_size=5)
    print(f"full q shape:    {tuple(q_full.shape)}")
    print(f"chunked q shape: {tuple(q_chunk.shape)}")
    print(f"full/chunk max q delta: {(q_full - q_chunk).abs().max().item():.6f}")
    print(f"full/chunk max k delta: {(k_full - k_chunk).abs().max().item():.6f}")


if __name__ == "__main__":
    main()
