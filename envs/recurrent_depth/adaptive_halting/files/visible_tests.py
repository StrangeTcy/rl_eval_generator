import torch

from halting import AdaptiveHaltingBlock


%%VISIBLE_TESTS%%


if __name__ == "__main__":
    test_shape = globals().get("test_shape") or globals().get("test_zero_and_one_steps")
    test_shape()
    print("Visible tests passed")
