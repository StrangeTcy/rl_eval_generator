from pipeline import %%MODEL_CLASS%%

def test_pipeline_ok():
    pipe = %%MODEL_CLASS%%()
    out = pipe.compose_pipeline(0.5)
    assert 0 <= out < 100
