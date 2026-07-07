import jinja2
from %%MODEL_FILE%% import %%MODEL_CLASS%%

def test_visible():
    engine = %%MODEL_CLASS%%()
    tpl_str = engine.get_template()
    
    ops = [
        {"symbol": "A", "repeat": 3, "skip": False},
        {"symbol": "X", "repeat": 5, "skip": True},
        {"symbol": "B", "repeat": 2, "skip": False}
    ]
    
    rendered = jinja2.Template(tpl_str).render(operations=ops).strip()
    assert rendered == "AAABB", f"Expected 'AAABB', got {rendered!r}"
    print("Visible tests passed!")

if __name__ == "__main__":
    test_visible()
