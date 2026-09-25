import torch

from recurrent_block import RecurrentBlock


def trusted_rollout(block, x, depth):
    state = x
    for _ in range(depth):
        state = block.transition(state)
    return state


if __name__ == "__main__":
    torch.manual_seed(0)
    block = RecurrentBlock(depth=%%TRAIN_DEPTH%%)
    x = torch.randn(%%BATCH_SIZE%%, 4)
    print(float(trusted_rollout(block, x, block.depth).mean()))
