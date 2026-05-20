import time

import torch
import torch.optim as optim
from torch.utils.data import DataLoader

from dataset import GlyphDataset, NUM_CLASSES
from model import GlyphCNN

EPOCHS = 10
BATCH_SIZE = 64


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    train_dataset = GlyphDataset(num_samples=10000, is_train=True)
    test_dataset  = GlyphDataset(num_samples=2000,  is_train=False)
    train_loader  = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    test_loader   = DataLoader(test_dataset,  batch_size=BATCH_SIZE)

    model     = GlyphCNN(num_classes=NUM_CLASSES).to(device)
    criterion = torch.nn.CrossEntropyLoss()
    %%OPT_LINE%%

    print("Starting training...")
    start = time.time()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        model.eval()
        correct = total = 0
        with torch.no_grad():
            for images, labels in test_loader:
                images, labels = images.to(device), labels.to(device)
                _, predicted = torch.max(model(images), 1)
                total   += labels.size(0)
                correct += (predicted == labels).sum().item()

        acc      = 100.0 * correct / total
        avg_loss = total_loss / len(train_loader)
        print(f"Epoch {epoch:2d}/{EPOCHS} | Loss: {avg_loss:.4f} | Acc: {acc:.2f}%")

    print(f"Training finished in {time.time() - start:.1f}s")
    torch.save(model.state_dict(), "glyph_model.pth")
    print("Model saved to glyph_model.pth")


if __name__ == "__main__":
    main()