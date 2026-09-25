import torch

from recurrent_block import CreditBlock


if __name__ == "__main__":
    torch.manual_seed(0)
    block = CreditBlock(depth=%%TRAIN_DEPTH%%)
    x = torch.randn(%%BATCH_SIZE%%, 4, requires_grad=True)
    loss = block(x).square().mean()
    loss.backward()
    print(float(loss), float(x.grad.norm()))
