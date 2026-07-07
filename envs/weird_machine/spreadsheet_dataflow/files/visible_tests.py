import re
from %%MODEL_FILE%% import %%MODEL_CLASS%%

def eval_sheet(inputs: list[float], formulas: dict[str, str]) -> dict[str, float]:
    values = {}
    for i, val in enumerate(inputs):
        values[f"A{i+1}"] = float(val)
        
    for i in range(1, len(inputs) + 1):
        cell = f"B{i}"
        f_str = formulas.get(cell, "")
        if not f_str.startswith("="):
            raise ValueError(f"Cell {cell} does not start with '=': {f_str!r}")
        expr = f_str[1:]
        # Replace MIN(...) with min(...)
        expr = re.sub(r'\bMIN\b', 'min', expr, flags=re.IGNORECASE)
        # Replace cell references like A1, B2 with values[cell]
        def repl(m):
            c = m.group(0).upper()
            if c in values:
                return str(values[c])
            raise ValueError(f"Unknown or uninitialized cell reference {c} in {cell}")
        eval_expr = re.sub(r'\b[AB]\d+\b', repl, expr, flags=re.IGNORECASE)
        values[cell] = float(eval(eval_expr, {"__builtins__": None, "min": min, "max": max}))
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
