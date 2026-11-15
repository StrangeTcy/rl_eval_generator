import re
from sheet_model import %%MODEL_CLASS%%

def eval_sheet(inputs: list[float], formulas: dict[str, str]) -> dict[str, float]:
    values = {}
    for i, val in enumerate(inputs):
        values[f"A{i+1}"] = float(val)
        
    for i in range(1, len(inputs) + 1):
        cell = f"B{i}"
        f_str = formulas.get(cell, "")
        if not f_str.startswith("="):
            raise ValueError(f"Cell {cell} does not start with '=': {f_str!r}")
        expr = re.sub(r"\s+", "", f_str[1:]).upper()
        parsed = re.fullmatch(r"(?:([AB][1-9][0-9]*)|MIN\(([AB][1-9][0-9]*),([AB][1-9][0-9]*)\))(?:\+(?:([AB][1-9][0-9]*)|MIN\(([AB][1-9][0-9]*),([AB][1-9][0-9]*)\)))?", expr)
        if parsed is None:
            raise ValueError("Formula must contain one or two cell/MIN terms joined by +")
        left = values[parsed.group(1)] if parsed.group(1) else min(values[parsed.group(2)], values[parsed.group(3)])
        right = values[parsed.group(4)] if parsed.group(4) else min(values[parsed.group(5)], values[parsed.group(6)]) if parsed.group(5) else 0.0
        values[cell] = left + right
    return values

def test_visible():
    engine = %%MODEL_CLASS%%()
    inputs = [10.0, 5.0, 2.0, 8.0]
    formulas = engine.build_dp_formulas(len(inputs))
    
    assert len(formulas) == 4, f"Expected 4 formulas, got {len(formulas)}"
    vals = eval_sheet(inputs, formulas)
    
    # B1 = 10
    # B2 = 5 + 10 = 15
    # B3 = 2 + min(15, 10) = 12
    # B4 = 8 + min(12, 15) = 20
    assert vals["B1"] == 10.0, f"Expected B1=10, got {vals['B1']}"
    assert vals["B2"] == 15.0, f"Expected B2=15, got {vals['B2']}"
    assert vals["B3"] == 12.0, f"Expected B3=12, got {vals['B3']}"
    assert vals["B4"] == 20.0, f"Expected B4=20, got {vals['B4']}"
    print("Visible tests passed!")

if __name__ == "__main__":
    test_visible()
