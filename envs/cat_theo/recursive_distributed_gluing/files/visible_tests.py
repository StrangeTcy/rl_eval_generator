from solver import %%MODEL_CLASS%%


def _visible():
    return {
        "modulus": 4,
        "input": 1,
        "lock_count": 1,
        "root": "root",
        "workers": {
            "root": {"parent": None, "child": "leaf", "program": ["spawn", "recv:child", "compute"]},
            "leaf": {"parent": "root", "child": None, "program": ["compute", "send:parent"]},
        },
    }


def test_lock_free_two_workers():
    out = %%MODEL_CLASS%%().solve(_visible())
    assert out["status"] == "sat"
    ops = [(ev["agent"], ev["op"]) for ev in out["trace"]]
    assert ("root", "spawn") in ops
    assert ("leaf", "compute") in ops
    assert ("leaf", "send:parent") in ops
    assert ("root", "recv:child") in ops


def test_deterministic():
    solver = %%MODEL_CLASS%%()
    inst = _visible()
    assert solver.solve(inst) == solver.solve(inst)


if __name__ == "__main__":
    test_lock_free_two_workers()
    test_deterministic()
    print("visible tests passed")
