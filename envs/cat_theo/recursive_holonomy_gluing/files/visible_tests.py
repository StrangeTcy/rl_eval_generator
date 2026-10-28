from solver import %%MODEL_CLASS%%


def _visible():
    return {
        "family": "multiplicative",
        "modulus": 7,
        "domain": [1, 2, 3, 4, 5, 6],
        "modules": {"leaf": {"ports": ["in", "out"], "child": None}},
        "root": "leaf",
        "depth": 1,
        "cycle": ["leaf"],
        "paths": {"path_a": ("leaf",), "path_b": ("leaf",)},
        "transport_edges": (("base", "base", "leaf"), ("base", "base", "leaf")),
        "calibration": {"leaf": [[1, 1]]},
        "representation": "revealed",
        "maps": {"leaf": {"q": 1}},
    }


def test_identity_has_a_returning_state():
    out = %%MODEL_CLASS%%().solve(_visible())
    assert out["status"] == "sat"
    assert out["state"] in _visible()["domain"]


def test_deterministic():
    solver = %%MODEL_CLASS%%()
    assert solver.solve(_visible()) == solver.solve(_visible())


if __name__ == "__main__":
    test_identity_has_a_returning_state()
    test_deterministic()
    print("visible tests passed")
