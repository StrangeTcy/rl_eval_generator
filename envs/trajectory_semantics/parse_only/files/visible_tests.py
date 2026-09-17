import task
from solution import solve


def test_parse():
    answer = solve(task.SPEC_TEXT, "parse_only")
    assert isinstance(answer, str)


def test_noisy_parse():
    assert solve(task.NOISY_SPEC_TEXT, "parse_only") == solve(task.SPEC_TEXT, "parse_only")


if __name__ == "__main__":
    test_parse()
    test_noisy_parse()
    print("Visible tests passed")
