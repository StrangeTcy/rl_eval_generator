%%DATA_DOCSTRING%%
import random
import math

import torch
from torch.utils.data import Dataset
from torchvision import transforms
from PIL import Image, ImageDraw

IMG_SIZE = 64
NUM_CLASSES = 10

%%CLASS_DEF_BLOCK%%


def draw_shape(draw, shape, pos, size, rotation, color="white"):
    x, y = pos
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    if shape == "circle":
        draw.ellipse([(x - size, y - size), (x + size, y + size)], fill=color)
    elif shape == "square":
        corners = [(-size, -size), (size, -size), (size, size), (-size, size)]
        rotated = [
            (px * cos_r - py * sin_r + x, px * sin_r + py * cos_r + y)
            for px, py in corners
        ]
        draw.polygon(rotated, fill=color)
    elif shape == "triangle":
        corners = [
            (0, -size),
            (-size * 0.866, size * 0.5),
            (size * 0.866, size * 0.5),
        ]
        rotated = [
            (px * cos_r - py * sin_r + x, px * sin_r + py * cos_r + y)
            for px, py in corners
        ]
        draw.polygon(rotated, fill=color)


def generate_glyph(class_id):
    """Draw one glyph image for the given class. Returns a PIL Image."""
    image = Image.new("L", (IMG_SIZE, IMG_SIZE), "black")
    draw = ImageDraw.Draw(image)
    for shape_type, count in CLASS_DEFS[class_id]:
        for _ in range(count):
            pos = (
                random.randint(12, IMG_SIZE - 12),
                random.randint(12, IMG_SIZE - 12),
            )
            size = random.randint(5, 10)
            rotation = random.uniform(0, 2 * math.pi)
            draw_shape(draw, shape_type, pos, size, rotation)
    return image


%%AUGMENT_CLASS%%


class GlyphDataset(Dataset):
    def __init__(self, num_samples, is_train=True):
        self.num_samples = num_samples
        self.is_train = is_train
        if self.is_train:
            %%AUGMENT_CALL%%
        else:
            self.augment = transforms.Compose([
                transforms.ToTensor(),
                transforms.Normalize((0.5,), (0.5,)),
            ])

    def __len__(self):
        return self.num_samples

    def __getitem__(self, idx):
        if not self.is_train:
            random.seed(idx)
        class_id = random.randint(0, NUM_CLASSES - 1)
        image = generate_glyph(class_id)
        image = self.augment(image)
        return image, torch.tensor(class_id, dtype=torch.long)