from solver import %%MODEL_CLASS%%


def _visible():
    return {
        "modulus": 5,
        "programs": [1, ["add", 1, 2]],
        "stages": [{"name": "front", "kind": "compile"}],
        "claimed_decoder": {0: "push", 1: "add", 2: "halt"},
        "calibration": [{"source": 1, "bytes": [[0, 1], [2]]}],
        "representation": "revealed",
        "encodings": {"front": {"push": 0, "add": 1, "halt": 2}},
    }


def test_claims_a_boolean():
    out = %%MODEL_CLASS%%().solve(_visible())
    assert type(out["equivalent"]) is bool


def test_deterministic():
    solver = %%MODEL_CLASS%%()
    assert solver.solve(_visible()) == solver.solve(_visible())


if __name__ == "__main__":
    test_claims_a_boolean()
    test_deterministic()
    print("visible tests passed")
