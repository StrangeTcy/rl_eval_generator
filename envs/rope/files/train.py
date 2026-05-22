"""Small smoke-training script for the RoPE environment."""
import torch
from model import TinyAttentionBlock


def main():
    torch.manual_seed(0)
    model = TinyAttentionBlock(dim=8, heads=2)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    for step in range(5):
        x = torch.randn(4, 16, 8)
        q, k = model(x)
        loss = (q.mean() - k.mean()).pow(2) + 0.001 * (q.square().mean() + k.square().mean())
        opt.zero_grad(); loss.backward(); opt.step()
        print(f"step {step} loss {loss.item():.6f}")
    torch.save(model.state_dict(), "rope_smoke.pth")


if __name__ == "__main__":
    main()
