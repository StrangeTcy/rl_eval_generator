import torch
import torchvision.transforms as transforms

class %%MODEL_CLASS%%:
    def __init__(self):
        self.transform = transforms.Compose([
            transforms.RandomAffine(degrees=15, shear=10),
        ])

    def augment(self, x, quarter_turns=0):
        return self.transform(x)
