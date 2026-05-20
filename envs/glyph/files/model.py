import torch
import torch.nn as nn

%%ARCH_EXTRA_CLASS%%


class GlyphCNN(nn.Module):
    def __init__(self, num_classes=10):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
        )
        %%ARCH_CLASSIFIER%%

    def forward(self, x):
        x = self.features(x)
        %%ARCH_FORWARD_HEAD%%
        return x


def load_model(path="glyph_model.pth"):
    model = GlyphCNN()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    model.eval()
    return model