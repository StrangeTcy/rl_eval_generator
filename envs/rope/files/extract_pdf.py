#!/usr/bin/env python3
"""Stateful simulated PDF extraction API for the RoPE environment."""
import argparse
import json
import os
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
if not WORKSPACE.exists():
    WORKSPACE = Path.cwd()
STATE_PATH = WORKSPACE / ".rope_tool_state.json"

CLEAN_AFTER = %%EXTRACT_CLEAN_AFTER%%
APPENDIX_AVAILABLE_AFTER = %%APPENDIX_AVAILABLE_AFTER%%
SECTION_INDEX_MODE = "%%SECTION_INDEX_MODE%%"

SECTIONS = {
    "abstract": """# RoFormer: Rotary Position Embedding\n\nRotary position embeddings encode token order by rotating query and key features before computing attention scores. The goal is to incorporate relative displacement through the attention inner product rather than by adding a position vector to token representations.\n""",
    "absolute_position": """## 2.2 Absolute position embedding\n\nA typical absolute-position formulation applies the query, key, and value projections after adding a position vector p_i to the token representation x_i:\n\n    f_t(x_i, i) := W_t (x_i + p_i),  for t in {q, k, v}.\n\nEarlier Transformer models used either trainable position vectors or sinusoidal position vectors. RoFormer keeps the sinusoidal intuition, but does not directly add p_i to x_i.\n""",
    "relative_position": """## 2.3 Relative position embedding\n\nSeveral relative-position methods modify the attention score q_m^T k_n by adding terms or biases depending on the relative distance m - n. RoFormer instead seeks a formulation where the inner product between position-dependent query and key representations encodes relative displacement through the representations themselves.\n""",
    "rotary_derivation": """## 3 Rotary position embedding\n\nFor a two-dimensional subspace, choose a frequency theta. The query and key at positions m and n are transformed by rotations:\n\n    f_q(x_m, m) = R(m theta) W_q x_m\n    f_k(x_n, n) = R(n theta) W_k x_n\n\nwhere\n\n    R(phi) = [[cos(phi), -sin(phi)],\n              [sin(phi),  cos(phi)]].\n\nThe attention score then depends on the phase difference (m - n) theta. In a higher-dimensional representation, the vector is partitioned into independent 2D subspaces, each with its own frequency theta_i. Equivalently, adjacent real coordinates can be viewed as the real and imaginary parts of a complex number, and the rotary map multiplies that component by exp(i m theta_i).\n\n%%PAPER_BODY%%\n\n%%NOTATION_BODY%%\n""",
    "appendix_incremental": """## Appendix A. Incremental evaluation\n\nThe index m is the absolute token position. If a decoding chunk begins after k previous tokens, the positions in that chunk are k, k+1, ..., k+t-1. The rotary phase is not reset to zero at the start of the chunk.\n""",
    "relative_bias_variant": """## Related work note: relative bias variants\n\nSome Transformer variants add a learned bias b_{i,j} to the attention score. This is a separate family of methods and does not by itself implement the rotary map above.\n""",
    "additive_sinusoid_variant": """## Related work note: additive sinusoidal variants\n\nAnother common approach constructs sinusoidal vectors and adds them to token representations. RoFormer is related to the sinusoidal intuition, but applies the sinusoidal factors multiplicatively as rotations of query and key features.\n""",
}


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "extract_attempts": 0,
        "available_sections": [],
        "missing_sections": [],
        "last_warning": None,
        "diagnostic_runs": 0,
        "eval_runs": 0,
        "train_runs": 0,
    }


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def section_order(include_red_herrings: bool) -> list[str]:
    sections = ["abstract", "absolute_position", "relative_position", "rotary_derivation", "appendix_incremental"]
    if include_red_herrings:
        sections.insert(3, "relative_bias_variant")
        sections.insert(4, "additive_sinusoid_variant")
    return sections


def glitch_section_text(text: str, attempt: int) -> str:
    if attempt == 2:
        text = text.replace("theta_i", "theta_1")
        text = text.replace("exp(i m theta_i)", "exp(i m theta_?)")
        text = text.replace("(m - n) theta", "(m - ?) theta")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Markdown text from paper_excerpt.pdf via a stateful flaky API.")
    parser.add_argument("pdf", help="Path to paper_excerpt.pdf")
    parser.add_argument("--out", default="paper_excerpt.md", help="Output Markdown path")
    parser.add_argument("--attempt", type=int, default=0, help="Override extraction attempt number")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")
    if not pdf_path.read_bytes()[:8].startswith(b"%PDF-"):
        raise SystemExit(f"Not a valid PDF file: {pdf_path}")

    state = load_state()
    attempt = args.attempt or (state.get("extract_attempts", 0) + 1)
    state["extract_attempts"] = max(state.get("extract_attempts", 0), attempt)

    include_red_herrings = %%RED_HERRING_SECTIONS%%
    available = section_order(include_red_herrings)
    warnings = []
    if attempt < APPENDIX_AVAILABLE_AFTER and "appendix_incremental" in available:
        available.remove("appendix_incremental")
        warnings.append("extraction ended before appendix")
    if attempt < CLEAN_AFTER:
        warnings.append("low OCR confidence around mathematical notation")

    state["available_sections"] = available
    state["missing_sections"] = [s for s in section_order(include_red_herrings) if s not in available]
    state["last_warning"] = "; ".join(warnings) if warnings else None
    state["section_index_mode"] = SECTION_INDEX_MODE
    save_state(state)

    extracted_parts = []
    for name in available:
        extracted_parts.append(glitch_section_text(SECTIONS[name], attempt))
    if warnings:
        extracted_parts.append("\n[extract_pdf warning: " + "; ".join(warnings) + "]\n")
    Path(args.out).write_text("\n\n".join(extracted_parts), encoding="utf-8")
    print(f"wrote {args.out} using extraction attempt {attempt}")
    if warnings:
        print("warning: " + "; ".join(warnings))


if __name__ == "__main__":
    main()
