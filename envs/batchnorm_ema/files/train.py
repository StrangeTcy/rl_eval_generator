"""
Training script — gradient accumulation with ResNet + BatchNorm.
Uses a deterministic procedural CIFAR-like dataset so runtime evaluation works
with Docker network disabled.
"""
import time

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

from model import ResNetBN

%%SYNC_IMPORT%%

BATCH_SIZE = 32
ACCUM_STEPS = %%ACCUM_STEPS%%
EPOCHS = %%EPOCHS%%
LR = 1e-3
DATASET_TYPE = "%%DATASET_TYPE%%"
NUM_CLASSES = %%NUM_CLASSES%%

%%OPT_COMMENT%%


class SyntheticCIFARDataset(Dataset):
    def __init__(self, num_samples=5000, num_classes=10, seed=0, train=True):
        self.num_classes = num_classes
        self.train = train
        gen = torch.Generator().manual_seed(seed)
        self.labels = torch.randint(0, num_classes, (num_samples,), generator=gen)
        self.data = torch.zeros(num_samples, 3, 32, 32)
        for i, label in enumerate(self.labels.tolist()):
            row = (label * 7) % 24
            col = (label * 11) % 24
            channel = label % 3
            self.data[i, channel, row:row + 8, col:col + 8] = 1.0
            self.data[i, (channel + 1) % 3, 4:12, (label * 3) % 24:(label * 3) % 24 + 8] = 0.5
        self.data += torch.randn(self.data.shape, generator=gen) * 0.08
        self.data = self.data.clamp(0.0, 1.0)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        x = self.data[idx].clone()
        if self.train:
            # lightweight deterministic-ish augmentation driven by DataLoader order
            if torch.rand(()) < 0.5:
                x = torch.flip(x, dims=(2,))
            sx = int(torch.randint(-2, 3, (1,)).item())
            sy = int(torch.randint(-2, 3, (1,)).item())
            x = torch.roll(x, shifts=(sx, sy), dims=(1, 2))
        x = (x - 0.5) / 0.5
        return x, self.labels[idx]


def get_loaders():
    n_train = 5000 if NUM_CLASSES <= 10 else 8000
    n_test = 2000
    train_ds = SyntheticCIFARDataset(n_train, NUM_CLASSES, seed=1234, train=True)
    test_ds = SyntheticCIFARDataset(n_test, NUM_CLASSES, seed=5678, train=False)
    return (
        DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0),
        DataLoader(test_ds, batch_size=256, shuffle=False, num_workers=0),
    )


def evaluate(model, loader, device):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            correct += (model(x).argmax(1) == y).sum().item()
            total += y.size(0)
    return correct / total


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device} | ACCUM_STEPS: {ACCUM_STEPS} | Dataset: {DATASET_TYPE}")
    train_loader, test_loader = get_loaders()
    model = ResNetBN().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=LR)
    start = time.time()
    for epoch in range(1, EPOCHS + 1):
        model.train()
        optimizer.zero_grad()
        total_loss = 0.0
        for step, (x, y) in enumerate(train_loader):
            x, y = x.to(device), y.to(device)
            %%SYNC_CONTEXT_OPEN%%
            out = model(x)
            loss = criterion(out, y) / ACCUM_STEPS
            loss.backward()
            total_loss += loss.item() * ACCUM_STEPS
            %%SYNC_CONTEXT_CLOSE%%
            if (step + 1) % ACCUM_STEPS == 0:
                optimizer.step()
                optimizer.zero_grad()
        acc = evaluate(model, test_loader, device)
        print(f"Epoch {epoch:2d}/{EPOCHS} | Loss: {total_loss/len(train_loader):.4f} | Acc: {acc*100:.2f}%")
    print(f"Finished in {time.time() - start:.1f}s")
    torch.save(model.state_dict(), "model.pth")


if __name__ == "__main__":
    main()
