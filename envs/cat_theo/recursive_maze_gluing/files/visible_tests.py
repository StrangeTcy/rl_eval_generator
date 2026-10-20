from solver import %%MODEL_CLASS%%


def test_single_corridor():
    maze = {
        "root": "hall",
        "depth": 1,
        "tiles": {
            "hall": {
                "rooms": ["in", "out"],
                "entrance": "in",
                "exit": "out",
                "edges": [{"from": "in", "to": "out", "flip": 0}],
                "shafts": [],
            }
        },
        "start_orientation": 0,
        "goal_orientation": 0,
        "nesting": {},
    }
    out = %%MODEL_CLASS%%().solve(maze)
    assert out["status"] == "sat"
    assert out["steps"][0]["op"] == "move"
    assert out["steps"][0]["to"] == "out"


def test_deterministic():
    maze = {
        "root": "hall",
        "depth": 1,
        "tiles": {
            "hall": {
                "rooms": ["in", "out"],
                "entrance": "in",
                "exit": "out",
                "edges": [{"from": "in", "to": "out", "flip": 0}],
                "shafts": [],
            }
        },
        "start_orientation": 0,
        "goal_orientation": 0,
        "nesting": {},
    }
    solver = %%MODEL_CLASS%%()
    assert solver.solve(maze) == solver.solve(maze)


if __name__ == "__main__":
    test_single_corridor()
    test_deterministic()
    print("visible tests passed")
