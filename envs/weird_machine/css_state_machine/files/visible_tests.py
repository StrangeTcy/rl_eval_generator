import re
from css_logic import %%MODEL_CLASS%%

def eval_css_logic(rules: list[tuple[str, dict]], checked_indices: set[int], n: int) -> dict[str, str]:
    computed = {"#out_even": "none", "#out_odd": "none"}
    for selector, decl in rules:
        if not re.fullmatch(r"\s*(?:#c[0-9]+(?::checked|:not\(:checked\))?\s*~\s*)+#out_(?:even|odd)\s*", selector):
            raise ValueError("Invalid Boolean-selector expression")
        if set(decl) != {"display"} or (decl["display"] != "block" and decl["display"] != "none"):
            raise ValueError("Only display: block or display: none is permitted")
        parts = [p.strip() for p in selector.split("~")]
        target = parts[-1]
        if target not in computed:
            continue
        match = True
        for cond in parts[:-1]:
            m = re.fullmatch(r"#c([0-9]+)(:checked|:not\(:checked\))?", cond)
            if not m:
                match = False
                break
            idx = int(m.group(1))
            if idx >= n:
                raise ValueError("Checkbox index outside the input range")
            if m.group(2) is None:
                continue
            is_negated = "not" in cond
            is_checked = idx in checked_indices
            if is_negated and is_checked:
                match = False
            if not is_negated and not is_checked:
                match = False
        if match:
            computed[target] = decl.get("display", "none")
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
