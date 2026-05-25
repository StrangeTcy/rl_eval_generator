"""MoCo-style contrastive model."""
import torch
import torch.nn as nn
from queue_ops import enqueue_keys


class _Backbone(nn.Module):
    """Small CNN backbone. Do not modify."""
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(1, 8,  3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(8, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Flatten(),
            nn.Linear(16 * 4 * 4, 32),
        )

    def forward(self, x):
        return self.net(x)


class %%MODEL_CLASS%%(nn.Module):
    def __init__(self, dim: int = 16, K: int = %%K%%, m: float = 0.99, tau: float = 0.07):
        super().__init__()
        self.K   = K
        self.m   = m
        self.tau = tau

        self.encoder_q = _Backbone()
        self.encoder_k = _Backbone()
        self.proj_q = nn.Sequential(nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, dim))
        self.proj_k = nn.Sequential(nn.Linear(32, 32), nn.ReLU(), nn.Linear(32, dim))

        for p_q, p_k in zip(self.encoder_q.parameters(), self.encoder_k.parameters()):
            p_k.data.copy_(p_q.data)
            p_k.requires_grad = False
        for p_q, p_k in zip(self.proj_q.parameters(), self.proj_k.parameters()):
            p_k.data.copy_(p_q.data)
            p_k.requires_grad = False

        self.register_buffer("%%QUEUE_ATTR%%", torch.randn(dim, K))
        self.%%QUEUE_ATTR%% = nn.functional.normalize(self.%%QUEUE_ATTR%%, dim=0)
        self.register_buffer("_ptr", torch.zeros(1, dtype=torch.long))

        %%DISTRACTOR_INIT%%

    @torch.no_grad()
    def _momentum_update(self):
        for p_q, p_k in zip(self.encoder_q.parameters(), self.encoder_k.parameters()):
            p_k.data.mul_(self.m).add_(p_q.data, alpha=1.0 - self.m)
        for p_q, p_k in zip(self.proj_q.parameters(), self.proj_k.parameters()):
            p_k.data.mul_(self.m).add_(p_q.data, alpha=1.0 - self.m)

    @torch.no_grad()
    def %%DEQUEUE_FN%%(self, keys: torch.Tensor):
        enqueue_keys(self.%%QUEUE_ATTR%%, self._ptr, keys)

    %%TEMP_HELPER%%

    def forward(self, im_q: torch.Tensor, im_k: torch.Tensor):
        %%Q_VAR%% = self.proj_q(self.encoder_q(im_q))
        %%DISTRACTOR_FORWARD%%
        %%TEMP_COMMENT%%
        %%TEMP_Q%%

        with torch.no_grad():
            self._momentum_update()
            %%K_VAR%% = self.proj_k(self.encoder_k(im_k))
            %%TEMP_K%%

        l_pos = torch.einsum("nc,nc->n",  [%%Q_VAR%%, %%K_VAR%%]).unsqueeze(1)
        l_neg = torch.einsum("nc,ck->nk", [%%Q_VAR%%, self.%%QUEUE_ATTR%%.clone().detach()])

        logits = torch.cat([l_pos, l_neg], dim=1)
        labels = torch.zeros(logits.shape[0], dtype=torch.long, device=logits.device)

        self.%%DEQUEUE_FN%%(%%K_VAR%%)
        return logits, labels