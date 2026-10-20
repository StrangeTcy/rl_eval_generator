from solver import %%MODEL_CLASS%%


def _visible():
    w = [[[1, 0], [0, 0]], [[0, 0], [0, 0]]]
    return {
        "spins": [0, 1],
        "regions": {"leaf": {"weights": w}},
        "tree": {"kind": "leaf", "name": "leaf"},
        "calibration": {"spin_pairs": [[0, 0], [1, 1]]},
        "representation": "revealed",
        "depth": 1,
        "label_perm": [0, 1],
    }


def test_returns_a_table():
    out = %%MODEL_CLASS%%().solve(_visible())
    assert len(out["table"]) == 2
    assert type(out["fixed"]) is bool


def test_deterministic():
    solver = %%MODEL_CLASS%%()
    assert solver.solve(_visible()) == solver.solve(_visible())


if __name__ == "__main__":
    test_returns_a_table()
    test_deterministic()
    print("visible tests passed")
