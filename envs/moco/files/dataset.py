"""
Synthetic 4-class dataset for contrastive representation learning.
Do not modify this file.
"""
import torch
from torch.utils.data import Dataset


class ShapesDataset(Dataset):
    def __init__(self, num_samples: int = 2000, contrastive: bool = True):
        self.contrastive = contrastive
        torch.manual_seed(42)
        self.data   = torch.zeros(num_samples, 1, 16, 16)
        self.labels = torch.randint(0, 4, (num_samples,))
        for i in range(num_samples):
            lbl = self.labels[i].item()
            r0  = 2 if lbl < 2 else 10
            c0  = 2 if lbl % 2 == 0 else 10
            self.data[i, 0, r0:r0 + 4, c0:c0 + 4] = 1.0

    @staticmethod
    def augment(x: torch.Tensor) -> torch.Tensor:
        x  = x + torch.randn_like(x) * 0.15
        sx, sy = torch.randint(-1, 2, (2,)).tolist()
        x  = torch.roll(x, shifts=(sx, sy), dims=(1, 2))
        return x.clamp(0.0, 1.0)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        img = self.data[idx]
        if self.contrastive:
            return self.augment(img), self.augment(img), self.labels[idx]
        return self.augment(img), self.labels[idx]