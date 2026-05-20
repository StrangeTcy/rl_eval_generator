"""Linear probe evaluation. Do not modify."""
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from dataset import ShapesDataset
from %%MODEL_MODULE%% import %%MODEL_CLASS%%

K = %%K%%


def main():
    model = %%MODEL_CLASS%%(dim=16, K=K)
    try:
        model.load_state_dict(
            torch.load("ckpt.pt", map_location="cpu", weights_only=True)
        )
    except FileNotFoundError:
        print("ERROR: ckpt.pt not found. Run train.py first.")
        return

    model.eval()
    for p in model.encoder_q.parameters():
        p.requires_grad = False

    probe     = nn.Linear(32, 4)
    criterion = nn.CrossEntropyLoss()
    opt       = torch.optim.Adam(probe.parameters(), lr=1e-2)

    train_ld = DataLoader(ShapesDataset(1000, contrastive=False), batch_size=64, shuffle=True)
    test_ld  = DataLoader(ShapesDataset(500,  contrastive=False), batch_size=64)

    probe.train()
    for _ in range(10):
        for x, y in train_ld:
            with torch.no_grad():
                feats = model.encoder_q(x)
            loss = criterion(probe(feats), y)
            opt.zero_grad(); loss.backward(); opt.step()

    probe.eval()
    correct = total = 0
    with torch.no_grad():
        for x, y in test_ld:
            correct += (probe(model.encoder_q(x)).argmax(1) == y).sum().item()
            total   += y.size(0)

    acc = correct / total
    print(f"Linear Probe Accuracy: {acc * 100:.2f}%")
    print("SUCCESS" if acc >= 0.85 else "FAIL — representations have collapsed")


if __name__ == "__main__":
    main()