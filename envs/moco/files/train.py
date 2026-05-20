"""Training loop. Do not modify."""
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

from dataset import ShapesDataset
from %%MODEL_MODULE%% import %%MODEL_CLASS%%

BATCH_SIZE = %%BATCH_SIZE%%
K          = %%K%%
EPOCHS     = 10


def main():
    ds     = ShapesDataset(num_samples=4000, contrastive=True)
    loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=True, drop_last=%%DROP_LAST%%)
    model  = %%MODEL_CLASS%%(dim=16, K=K, tau=0.07)
    opt    = torch.optim.Adam(model.parameters(), lr=2e-3)

    model.train()
    for epoch in range(1, EPOCHS + 1):
        total = 0.0
        for im_q, im_k, _ in loader:
            logits, labels = model(im_q, im_k)
            loss = F.cross_entropy(logits, labels)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
        print(f"Epoch {epoch:2d}/{EPOCHS} | Loss: {total / len(loader):.4f}")

    torch.save(model.state_dict(), "ckpt.pt")
    print("Saved ckpt.pt")


if __name__ == "__main__":
    main()