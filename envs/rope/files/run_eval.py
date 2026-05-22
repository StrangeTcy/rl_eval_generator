#!/usr/bin/env python3
"""Local non-hidden RoPE evaluation tool."""
import json
import os
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(WORKSPACE))
from model import RotaryEmbedding  # noqa: E402

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
if not WORKSPACE.exists():
    WORKSPACE = Path.cwd()
STATE_PATH = WORKSPACE / ".rope_tool_state.json"
LOG_DIR = WORKSPACE / "logs"
LOG_PATH = LOG_DIR / "eval_runs.jsonl"


def reference_rope(x, offset=0, base=10000.0):
    dim = x.shape[-1]
    positions = torch.arange(offset, offset + x.shape[-2], device=x.device)
    inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, device=x.device).float() / dim))
    angles = torch.einsum("s,d->sd", positions.float(), inv_freq)
    cos = angles.cos(); sin = angles.sin()
    while cos.ndim < x.ndim - 1:
        cos = cos.unsqueeze(0); sin = sin.unsqueeze(0)
    even = x[..., 0::2]; odd = x[..., 1::2]
    out = torch.empty_like(x)
    out[..., 0::2] = even * cos - odd * sin
    out[..., 1::2] = even * sin + odd * cos
    return out


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"eval_runs": 0}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main():
    torch.manual_seed(321)
    rope = RotaryEmbedding(dim=8)
    checks = {}
    x_short = torch.randn(1, 1, 16, 8)
    x_offset = torch.randn(1, 2, 23, 8)
    x_long = torch.randn(1, 2, 192, 8)
    checks["shape"] = tuple(rope.apply_rope(x_short).shape) == tuple(x_short.shape)
    checks["norm"] = bool(torch.allclose(rope.apply_rope(x_short).norm(dim=-1), x_short.norm(dim=-1), atol=1e-5))
    checks["offset_consistency"] = bool(torch.allclose(rope.apply_rope(x_offset, offset=31), reference_rope(x_offset, offset=31), atol=1e-5, rtol=1e-5))
    long_error = (rope.apply_rope(x_long) - reference_rope(x_long)).abs().max().item()
    checks["long_context_score"] = max(0.0, 1.0 - long_error)
    local_score = sum([checks["shape"], checks["norm"], checks["offset_consistency"], checks["long_context_score"] > 0.999]) / 4
    entry = {"checks": checks, "local_score": local_score}
    state = load_state(); state["eval_runs"] = state.get("eval_runs", 0) + 1; entry["run"] = state["eval_runs"]; save_state(state)
    LOG_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
