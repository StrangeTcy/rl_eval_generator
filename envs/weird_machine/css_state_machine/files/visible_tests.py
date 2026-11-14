import re
from %%MODEL_MODULE%% import %%MODEL_CLASS%%

def eval_css_logic(rules: list[tuple[str, dict]], checked_indices: set[int], n: int) -> dict[str, str]:
    computed = {"#out_even": "none", "#out_odd": "none"}
    even_specificity = (-1, -1)
    odd_specificity = (-1, -1)
    for selector, decl in rules:
        parts = [p.strip() for p in selector.split("~")]
        target = parts[-1]
        if target not in computed:
            continue
        match = True
        previous_idx = -1
        specificity = (1, 0)
        for cond in parts[:-1]:
            m = re.fullmatch(r"#c(\d+)(:checked|:not\(:checked\))?", cond)
            if not m:
                match = False
                break
            idx = int(m.group(1))
            if not 0 <= idx < n or idx <= previous_idx:
                match = 0
                break
            previous_idx = idx
            specificity = (specificity[0] + 1, specificity[1] + (1 if m.group(2) else 0))
            is_negated = "not" in cond
            is_checked = idx in checked_indices
            if is_negated and is_checked:
                match = False
                break
            if m.group(2) and not is_negated and not is_checked:
                match = False
                break
        if match:
            if decl.get("display") != "block" and decl.get("display") != "none":
                raise ValueError("Only display: block or display: none is supported")
            if target == "#out_even" and specificity >= even_specificity:
                computed[target] = decl["display"]
                even_specificity = specificity
            elif target == "#out_odd" and specificity >= odd_specificity:
                computed[target] = decl["display"]
                odd_specificity = specificity
    return computed

def test_visible():
    engine = %%MODEL_CLASS%%()
    rules = engine.generate_parity_rules(2)
    assert isinstance(rules, list), "Must return a list of rules"
    
    # Check 0 checked -> even
    out = eval_css_logic(rules, set(), 2)
    assert out["#out_even"] == "block" and out["#out_odd"] != "block", f"Expected even for set(), got {out}"
    
    # Check 1 checked -> odd
    out = eval_css_logic(rules, {0}, 2)
    assert out["#out_odd"] == "block" and out["#out_even"] != "block", f"Expected odd for {{0}}, got {out}"
    print("Visible tests passed!")

if __name__ == "__main__":
    test_visible()
