#!/usr/bin/env python3
"""Local non-hidden RoPE evaluation tool."""
import json
import sys

import torch

from tool_state import EVAL_LOG, WORKSPACE, append_jsonl, load_state, log_event, save_state

sys.path.insert(0, str(WORKSPACE))
from rope import RotaryEmbedding  # noqa: E402
from model import TinyRoPEModel  # noqa: E402


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


def main():
    torch.manual_seed(321)
    rope = RotaryEmbedding(dim=8)
    model = TinyRoPEModel(dim=8, heads=2)
    checks = {}
    x_short = torch.randn(1, 1, 16, 8)
    x_offset = torch.randn(1, 2, 23, 8)
    x_long = torch.randn(1, 2, 192, 8)
    x_model = torch.randn(2, 37, 8)
    checks["shape"] = tuple(rope.apply_rope(x_short).shape) == tuple(x_short.shape)
    checks["norm"] = bool(torch.allclose(rope.apply_rope(x_short).norm(dim=-1), x_short.norm(dim=-1), atol=1e-5))
    checks["offset_consistency"] = bool(torch.allclose(rope.apply_rope(x_offset, offset=31), reference_rope(x_offset, offset=31), atol=1e-5, rtol=1e-5))
    long_error = (rope.apply_rope(x_long) - reference_rope(x_long)).abs().max().item()
    checks["long_context_score"] = max(0.0, 1.0 - long_error)
    q_full, k_full = model.forward_full(x_model)
    q_chunk, k_chunk = model.forward_chunked(x_model, chunk_size=7)
    checks["chunked_equivalence"] = bool(torch.allclose(q_full, q_chunk, atol=1e-5, rtol=1e-5) and torch.allclose(k_full, k_chunk, atol=1e-5, rtol=1e-5))
    local_score = sum([checks["shape"], checks["norm"], checks["offset_consistency"], checks["long_context_score"] > 0.999, checks["chunked_equivalence"]]) / 5
    entry = {"checks": checks, "local_score": local_score}
    state = load_state()
    state["eval_runs"] = state.get("eval_runs", 0) + 1
    entry["run"] = state["eval_runs"]
    save_state(state)
    append_jsonl(EVAL_LOG, entry)
    log_event("run_eval", "local_eval", "ok" if local_score >= 1.0 else "fail", f"local_score={local_score:.3f}", **entry)
    print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
