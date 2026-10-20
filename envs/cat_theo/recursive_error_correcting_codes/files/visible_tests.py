from solver import %%MODEL_CLASS%%


def _visible():
    return {
        "modulus": 5,
        "blocks": {"A": {"length": 2, "H": [[1, 1]]}},
        "glues": [],
        "parent_check": {"vars": [["A", 0], ["A", 1]], "row": [1, 1], "rhs": 0},
        "calibration": {"A": [[0, 0], [1, 4]]},
        "representation": "revealed",
        "depth": 1,
        "perms": {"A": [0, 1]},
    }


def test_local_block():
    out = %%MODEL_CLASS%%().solve(_visible())
    assert out["status"] == "sat"
    assert "A" in out["blocks"]


def test_deterministic():
    solver = %%MODEL_CLASS%%()
    assert solver.solve(_visible()) == solver.solve(_visible())


if __name__ == "__main__":
    test_local_block()
    test_deterministic()
    print("visible tests passed")
