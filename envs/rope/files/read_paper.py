#!/usr/bin/env python3
"""Read sections from the current extracted paper state."""
import argparse

from tool_state import load_state, log_event

SECTION_TITLES = {
    "abstract": "Abstract / overview",
    "absolute_position": "2.2 Absolute position embedding",
    "relative_position": "2.3 Relative position embedding",
    "relative_bias_variant": "Related work: relative bias variants",
    "additive_sinusoid_variant": "Related work: additive sinusoidal variants",
    "rotary_derivation": "3 Rotary position embedding",
    "appendix_incremental": "Appendix A: incremental evaluation",
}

SECTION_TEXT = {
    "abstract": """RoFormer introduces rotary position embeddings, which encode token position by rotating query and key representations before the attention dot product.""",
    "absolute_position": """Absolute-position methods add p_i to x_i before projection: f_t(x_i, i) := W_t (x_i + p_i). This section is useful background but does not describe the final rotary implementation.""",
    "relative_position": """Relative-position methods often add learned terms or biases depending on m - n. RoFormer instead derives a multiplicative rotational form for query and key vectors.""",
    "relative_bias_variant": """A learned relative bias b_{i,j} can be added to attention logits. This is a plausible but different method; it does not repair a wrong rotary transform.""",
    "additive_sinusoid_variant": """Sinusoidal vectors may be added to representations in absolute-position methods. RoPE uses sinusoidal factors as rotations rather than additive embeddings.""",
    "rotary_derivation": """For a two-dimensional subspace, RoPE applies R(m theta) to the query at position m and R(n theta) to the key at position n. R(phi) = [[cos(phi), -sin(phi)], [sin(phi), cos(phi)]]. In higher dimensions, independent two-dimensional subspaces use frequencies theta_i. Adjacent real coordinates correspond to each complex component.""",
    "appendix_incremental": """During incremental evaluation, m is the absolute token position. A chunk beginning after k previous tokens uses positions k, k+1, ..., k+t-1; the rotary phase is not reset at the start of the chunk.""",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Read an extracted paper section.")
    parser.add_argument("section", help="Section name, or 'index', or 'all'")
    args = parser.parse_args()
    state = load_state()
    available = state.get("available_sections", [])
    mode = state.get("section_index_mode", "standard")

    if args.section == "index":
        if mode == "clear":
            for name in available:
                print(f"{name}: {SECTION_TITLES.get(name, name)}")
        elif mode == "opaque":
            for i, name in enumerate(available, 1):
                print(f"section_{i}: {SECTION_TITLES.get(name, name)} [{name}]")
        else:
            for name in available:
                print(name)
        if state.get("missing_sections"):
            print("\nMissing from current extraction:")
            for name in state["missing_sections"]:
                print(f"- {name}")
        if state.get("last_warning"):
            print("\nwarning: " + state["last_warning"])
        log_event("read_paper", "index", "ok", "listed paper sections", available_sections=available, missing_sections=state.get("missing_sections", []))
        return

    sections = available if args.section == "all" else [args.section]
    for name in sections:
        if name not in available:
            log_event("read_paper", "read_section", "error", f"section unavailable: {name}", section=name)
            raise SystemExit(f"Section {name!r} is not available in the current extraction. Try extracting again or inspect the index.")
        print(f"# {SECTION_TITLES.get(name, name)}\n")
        print(SECTION_TEXT[name])
        print()
        log_event("read_paper", "read_section", "ok", f"read {name}", section=name)


if __name__ == "__main__":
    main()
