#!/usr/bin/env python3
"""Stateful train-like diagnostics for the current RoPE implementation."""
import argparse
import json
import sys

import torch

from tool_state import TRAIN_LOG, WORKSPACE, append_jsonl, load_state, log_event, save_state

sys.path.insert(0, str(WORKSPACE))
from rope import RotaryEmbedding  # noqa: E402
from model import TinyRoPEModel  # noqa: E402

FEEDBACK_MODE = "%%FEEDBACK_MODE%%"
TRAIN_HINT_TEXT = "%%TRAIN_HINT_TEXT%%"


def reference_rope(x, offset=0, base=10000.0):
    dim = x.shape[-1]
    positions = torch.arange(offset, offset + x.shape[-2], device=x.device)
    inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2, device=x.device).float() / dim))
    angles = torch.einsum("s,d->sd", positions.float(), inv_freq)
    cos = angles.cos()
    sin = angles.sin()
    while cos.ndim < x.ndim - 1:
        cos = cos.unsqueeze(0)
        sin = sin.unsqueeze(0)
    even = x[..., 0::2]
    odd = x[..., 1::2]
    out = torch.empty_like(x)
    out[..., 0::2] = even * cos - odd * sin
    out[..., 1::2] = even * sin + odd * cos
    return out


def metric(config: str):
    torch.manual_seed(100 + len(config))
    if config == "short":
        rope = RotaryEmbedding(dim=8)
        x = torch.randn(1, 1, 8, 8)
        expected = reference_rope(x)
        actual = rope.apply_rope(x)
        category = "pairing_or_frequency" if not torch.allclose(actual, expected, atol=1e-5, rtol=1e-5) else "none"
        max_error = (actual - expected).abs().max().item()
    elif config == "offset":
        rope = RotaryEmbedding(dim=8)
        x = torch.randn(1, 2, 19, 8)
        expected = reference_rope(x, offset=17)
        actual = rope.apply_rope(x, offset=17)
        category = "cached_position_shift" if not torch.allclose(actual, expected, atol=1e-5, rtol=1e-5) else "none"
        max_error = (actual - expected).abs().max().item()
    elif config == "long":
        rope = RotaryEmbedding(dim=8)
        x = torch.randn(1, 2, 256, 8)
        expected = reference_rope(x)
        actual = rope.apply_rope(x)
        category = "phase_drift" if not torch.allclose(actual, expected, atol=1e-5, rtol=1e-5) else "none"
        max_error = (actual - expected).abs().max().item()
    elif config == "chunked":
        model = TinyRoPEModel(dim=8, heads=2)
        x = torch.randn(2, 37, 8)
        q_full, k_full = model.forward_full(x)
        q_chunk, k_chunk = model.forward_chunked(x, chunk_size=7)
        max_error = max((q_full - q_chunk).abs().max().item(), (k_full - k_chunk).abs().max().item())
        category = "cross_file_offset_propagation" if max_error > 1e-5 else "none"
    else:
        raise SystemExit("config must be one of: short, offset, long, chunked, all")
    score = max(0.0, 1.0 - max_error)
    return {"config": config, "max_error": max_error, "score": score, "category": category, "status": "pass" if category == "none" else "fail"}


def print_entry(entry: dict) -> None:
    if FEEDBACK_MODE == "hint" and entry["status"] == "fail":
        print(TRAIN_HINT_TEXT.format(**entry))
    elif FEEDBACK_MODE == "summary":
        print(f"{entry['config']}: {entry['status']} ({entry['category']})")
    else:
        print(json.dumps({k: entry[k] for k in ["config", "max_error", "score", "status"]}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run train-like RoPE diagnostics.")
    parser.add_argument("config", choices=["short", "offset", "long", "chunked", "all"])
    args = parser.parse_args()
    configs = ["short", "offset", "long", "chunked"] if args.config == "all" else [args.config]
    state = load_state()
    for cfg in configs:
        entry = metric(cfg)
        state["train_runs"] = state.get("train_runs", 0) + 1
        entry["run"] = state["train_runs"]
        if entry["status"] == "fail":
            state.setdefault("observed_failures", []).append(entry["category"])
        append_jsonl(TRAIN_LOG, entry)
        log_event("run_train", "diagnostic", entry["status"], f"{cfg}: {entry['status']} {entry['category']}", **entry)
        print_entry(entry)
    save_state(state)


if __name__ == "__main__":
    main()
