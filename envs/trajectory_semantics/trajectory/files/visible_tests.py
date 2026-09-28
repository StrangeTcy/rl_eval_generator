import task
from solution import solve


def test_zero_horizon():
    assert solve(task.SPEC_TEXT, "A", 0, 0) == ("A", 0)


def test_one_step():
    assert solve(task.SPEC_TEXT, "A", 0, 1) == ("B", 0)


if __name__ == "__main__":
    test_zero_horizon()
    test_one_step()
    print("Visible tests passed")
