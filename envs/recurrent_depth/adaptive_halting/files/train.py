import torch

from halting import AdaptiveHaltingBlock


if __name__ == "__main__":
    torch.manual_seed(0)
    block = AdaptiveHaltingBlock()
    x = torch.randn(%%BATCH_SIZE%%, 4)
    counts = torch.arange(%%BATCH_SIZE%%) % (%%TRAIN_DEPTH%% + 1)
    print(float(block(x, counts).mean()))
