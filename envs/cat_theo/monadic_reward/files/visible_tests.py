from monad import StateMonad
from agent_code import %%MODEL_CLASS%%

def test_computation():
    verifier = %%MODEL_CLASS%%()
    m = verifier.compute("(5, 10)")
    val, state = m.run_fn([])
    assert val == 6
