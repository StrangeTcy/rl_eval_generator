from solver import %%MODEL_CLASS%%


def _identity_tables(labels):
    pairs = [[lab, lab] for lab in labels]
    return {"enter": [list(p) for p in pairs], "mid": [list(p) for p in pairs], "leave": [list(p) for p in pairs]}


def _depth1_tree():
    labels = ["s0", "s1", "s2"]
    pairs = [[lab, lab] for lab in labels]
    wiring = _identity_tables(labels)
    return {
        "root": "stem",
        "depth": 1,
        "modules": {
            "stem": {"kind": "branch", "ports": ["enter", "leave"], "ports_domain": list(labels)},
            "tip": {
                "kind": "leaf",
                "ports": ["enter", "leave"],
                "ports_domain": list(labels),
                "pairs": pairs,
            },
        },
        "productions": {
            "stem": {
                "deeper": {"left": "stem", "right": "stem", "wiring": wiring},
                "depth_1": {"left": "tip", "right": "tip", "wiring": wiring},
            }
        },
        "closing": None,
    }


def test_depth1_identity_tree_is_sat():
    grammar = _depth1_tree()
    out = %%MODEL_CLASS%%().solve(grammar)
    assert out["status"] == "sat"
    assert [out["root_enter"], out["root_leave"]] in [["s0", "s0"], ["s1", "s1"], ["s2", "s2"]]
    tip_pairs = out["realizable"]["tip"]["0"]
    stem_pairs = out["realizable"]["stem"]["1"]
    assert ["s0", "s0"] in [list(p) for p in tip_pairs]
    assert ["s0", "s0"] in [list(p) for p in stem_pairs]


def test_leaf_pairs_are_reported():
    grammar = _depth1_tree()
    out = %%MODEL_CLASS%%().solve(grammar)
    reported = sorted(list(p) for p in out["realizable"]["tip"]["0"])
    assert reported == [["s0", "s0"], ["s1", "s1"], ["s2", "s2"]]


def test_deterministic():
    grammar = _depth1_tree()
    solver = %%MODEL_CLASS%%()
    assert solver.solve(grammar) == solver.solve(grammar)


if __name__ == "__main__":
    test_depth1_identity_tree_is_sat()
    test_leaf_pairs_are_reported()
    test_deterministic()
    print("visible tests passed")
