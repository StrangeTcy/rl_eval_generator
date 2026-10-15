from solver import %%MODEL_CLASS%%


def test_two_region_full_table():
    instance = {
        "regions": {
            "cell_a": {"domain": ["p", "q"], "cycle": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"], "cycle": ["r", "s"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]},
        ],
        "copies": [],
        "gadget": "cell_a",
    }
    out = %%MODEL_CLASS%%().solve(instance)
    assert out["status"] == "sat"
    assert out["assignment"]["cell_a"] == "p"
    assert out["assignment"]["cell_b"] == "r"


def test_three_region_path():
    instance = {
        "regions": {
            "cell_a": {"domain": ["p", "q"], "cycle": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"], "cycle": ["r", "s"]},
            "cell_c": {"domain": ["t", "u"], "cycle": ["t", "u"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]},
            {"left": "cell_b", "right": "cell_c", "pairs": [["r", "t"], ["s", "u"]]},
        ],
        "copies": [],
        "gadget": "cell_a",
    }
    out = %%MODEL_CLASS%%().solve(instance)
    assert out["status"] == "sat"
    asg = out["assignment"]
    assert [asg["cell_a"], asg["cell_b"]] in [["p", "r"], ["q", "s"]]
    assert [asg["cell_b"], asg["cell_c"]] in [["r", "t"], ["s", "u"]]


def test_deterministic():
    instance = {
        "regions": {
            "cell_a": {"domain": ["p", "q"], "cycle": ["p", "q"]},
            "cell_b": {"domain": ["r", "s"], "cycle": ["r", "s"]},
        },
        "overlaps": [
            {"left": "cell_a", "right": "cell_b", "pairs": [["p", "r"], ["q", "s"]]},
        ],
        "copies": [],
        "gadget": "cell_a",
    }
    solver = %%MODEL_CLASS%%()
    assert solver.solve(instance) == solver.solve(instance)


if __name__ == "__main__":
    test_two_region_full_table()
    test_three_region_path()
    test_deterministic()
    print("visible tests passed")
