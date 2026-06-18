from lenses import %%MODEL_CLASS%%

def test_view():
    lens = %%MODEL_CLASS%%()
    s = (1.0, 2.0)
    assert lens.view(s) == 1.0
