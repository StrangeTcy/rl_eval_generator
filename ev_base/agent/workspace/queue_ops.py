"""Queue update helper for the contrastive memory bank."""
import torch


@torch.no_grad()
def enqueue_keys(queue: torch.Tensor, ptr: torch.Tensor, keys: torch.Tensor) -> None:
    """
    Insert keys into a FIFO queue and advance ptr.

    BUG: when ptr + batch_size > K, this slice assignment silently truncates
    and drops tail keys instead of wrapping around.
    """
    n = keys.shape[0]
    k = queue.shape[1]
    start = int(ptr[0])
    queue[:, start:start + n] = keys.T
    ptr[0] = (start + n) % k
