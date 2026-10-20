from solver import %%MODEL_CLASS%%


def _visible():
    return {
        "agents": ["ann", "bob"],
        "frames": {
            "leaf": {
                "worlds": ["here"],
                "atoms": {"p": ["here"]},
                "indist": {"ann": [["here"]], "bob": [["here"]]},
            }
        },
        "levels": ["leaf"],
        "actual": ["here"],
        "query": "p",
        "bundle": None,
        "nested_bundle": None,
    }


def test_atom_at_actual_world():
    out = %%MODEL_CLASS%%().solve(_visible())
    assert out["query_value"] is True
    assert "bundle_possible" not in out


def test_deterministic():
    solver = %%MODEL_CLASS%%()
    assert solver.solve(_visible()) == solver.solve(_visible())


if __name__ == "__main__":
    test_atom_at_actual_world()
    test_deterministic()
    print("visible tests passed")
