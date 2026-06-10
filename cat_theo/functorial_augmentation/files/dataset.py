import torch
import torchvision.transforms as transforms

class %%MODEL_CLASS%%:
    def __init__(self):
        # BUG: Random affine shear and crop break translation/rotation symmetry.
        # This breaks discrete 90-degree rotation invariance of downstream layers.
        self.transform = transforms.Compose([
            transforms.RandomAffine(degrees=15, shear=10),
        ])

    def augment(self, x: torch.Tensor) -> torch.Tensor:
        # Applying the non-functorial transforms
        return self.transform(x)
