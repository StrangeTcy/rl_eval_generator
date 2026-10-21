from solver import %%MODEL_CLASS%%


def test_two_region_unique_pair():
    instance = {
        "regions": {
            "cell_a": {"domain": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"]]},
        ],
    }
    out = %%MODEL_CLASS%%().solve(instance)
    assert out["status"] == "sat"
    assert out["assignment"]["cell_a"] == "p"
    assert out["assignment"]["cell_b"] == "r"


def test_three_region_path():
    instance = {
        "regions": {
            "cell_a": {"domain": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"]},
            "cell_c": {"domain": ["t", "u"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]},
            {"left": "cell_b", "right": "cell_c", "pairs": [["r", "t"], ["s", "u"]]},
        ],
    }
    out = %%MODEL_CLASS%%().solve(instance)
    assert out["status"] == "sat"
    asg = out["assignment"]
    assert asg["cell_a"] in {"p", "q"}
    assert [asg["cell_a"], asg["cell_b"]] in [["p", "r"], ["q", "s"]]
    assert [asg["cell_b"], asg["cell_c"]] in [["r", "t"], ["s", "u"]]


def test_deterministic_on_visible_path():
    instance = {
        "regions": {
            "cell_a": {"domain": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]},
        ],
    }
    solver = %%MODEL_CLASS%%()
    first = solver.solve(instance)
    second = solver.solve(instance)
    assert first == second


if __name__ == "__main__":
    test_two_region_unique_pair()
    test_three_region_path()
    test_deterministic_on_visible_path()
    print("visible tests passed")
