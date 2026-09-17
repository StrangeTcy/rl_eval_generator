#!/usr/bin/env python3
"""Hidden checks for per-example adaptive halting."""
from __future__ import annotations

import sys

import torch

from judge_lib import (
    base_result,
    emit,
    make_workdir,
    mark_check,
    require_changed_files,
    set_failure,
    validate_submission,
)

TRAIN_DEPTH = %%TRAIN_DEPTH%%
HIDDEN_DEPTH = %%HIDDEN_DEPTH%%
TOTAL_CHECKS = %%SCORING_TOTAL_CHECKS%%


def reference(block, x, counts):
    state = x
    for step in range(int(counts.max().item()) if counts.numel() else 0):
        candidate = block.transition(state)
        active = (counts > step).unsqueeze(-1)
        state = torch.where(active, candidate, state)
    return state


def main() -> None:
    result = base_result(training_completed=True, model_saved=True, total_checks=TOTAL_CHECKS)
    patched_dir = validate_submission(result)
    require_changed_files(result, {"halting.py"})
    try:
        workdir, _ = make_workdir(patched_dir)
        sys.path.insert(0, workdir)
        from halting import AdaptiveHaltingBlock

        torch.manual_seed(23)
        block = AdaptiveHaltingBlock(4, 4)
        x = torch.randn(5, 4)
        counts = torch.tensor([0, 1, 2, TRAIN_DEPTH, HIDDEN_DEPTH], dtype=torch.long)
        counts[-1] = min(counts[-1], HIDDEN_DEPTH)
        checks = {}

        expected = reference(block, x, counts)
        actual = block(x, counts)
        checks["per_example_halting"] = torch.equal(actual, expected)

        permutation = torch.tensor([4, 1, 3, 0, 2])
        checks["permutation_equivariance"] = torch.equal(
            block(x[permutation], counts[permutation]), actual[permutation]
        )

        changed = x.clone()
        changed[0] += 10.0
        changed_out = block(changed, counts)
        checks["no_cross_example_leakage"] = torch.equal(changed_out[1:], actual[1:])

        one = torch.randn(3, 4)
        one_count = torch.tensor([0, 1, 2])
        one_expected = reference(block, one, one_count)
        one_actual = block(one, one_count)
        checks["exact_off_by_one"] = torch.equal(one_actual, one_expected)

        grad_x = torch.randn(4, 4, requires_grad=True)
        grad_counts = torch.tensor([1, 2, 3, 4])
        loss = block(grad_x, grad_counts).square().mean()
        loss.backward()
        checks["valid_active_gradients"] = (
            grad_x.grad is not None
            and torch.isfinite(grad_x.grad).all().item()
            and block.transition.weight.grad is not None
            and torch.isfinite(block.transition.weight.grad).all().item()
        )

        passed = 0
        for name, value in checks.items():
            mark_check(result, name, bool(value))
            passed += int(bool(value))
        result["passed_checks"] = passed
        result["score"] = passed / TOTAL_CHECKS
    except Exception as exc:
        set_failure(result, "RUNTIME_ERROR", str(exc))
        result["score"] = 0.0
    emit(result)


if __name__ == "__main__":
    main()
