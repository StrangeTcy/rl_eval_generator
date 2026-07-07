import sys
from %%MODEL_FILE%% import %%MODEL_CLASS%%

def test_visible():
    engine = %%MODEL_CLASS%%()
    # Test simple patterns
    # For "1": padded to "010" -> neighborhood for cell 0 is 010 -> 1. Output: "1"
    assert engine.step("1") == "1", f"Expected '1', got {engine.step('1')!r}"
    
    # For "001":
    # cell 0: 000 -> 0
    # cell 1: 001 -> 1
    # cell 2: 010 -> 1
    # Output: "011"
    out = engine.step("001")
    assert out == "011", f"Expected '011' for '001', got {out!r}"
    print("Visible tests passed!")

if __name__ == "__main__":
    test_visible()
