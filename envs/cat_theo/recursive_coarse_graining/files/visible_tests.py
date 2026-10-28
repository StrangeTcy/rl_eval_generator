from solver import %%MODEL_CLASS%%


def _visible():
    w = [[[1, 0], [0, 0]], [[0, 0], [0, 0]]]
    return {
        "abstraction": (((3, 4, 5, 0, 1, 2), (1, 2, 0, 1, 2, 0)),
                        ((0, 0), (3, 1)), ((0, (0, 1, 0)), (5, (1, 0)))),
        "spins": [0, 1],
        "regions": {"leaf": {"weights": w}},
        "tree": {"kind": "leaf", "name": "leaf"},
        "calibration": {"spin_pairs": [[0, 0], [1, 1]],
                        "probe_table": ((1, 2), (3, 4)), "observed_probe_table": ((1, 2), (3, 4))},
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
