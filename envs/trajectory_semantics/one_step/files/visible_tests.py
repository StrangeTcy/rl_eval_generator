import task
from solution import solve


def test_one_step_contract():
    result = solve(task.SPEC_TEXT, "A", 0)
    assert isinstance(result, tuple) and len(result) == 2


def test_format_variant():
    assert solve(task.SPEC_TEXT, "A", 0) == solve(task.NOISY_SPEC_TEXT, "A", 0)


if __name__ == "__main__":
    test_one_step_contract()
    test_format_variant()
    print("Visible tests passed")
