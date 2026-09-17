#!/usr/bin/env python3
"""Hidden checks for the weight-tied recurrent state-carry task."""
from __future__ import annotations

import os
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


def rollout(block, x, depth):
    state = x
    for _ in range(depth):
        state = block.transition(state)
    return state


def main() -> None:
    result = base_result(training_completed=True, model_saved=True, total_checks=TOTAL_CHECKS)
    patched_dir = validate_submission(result)
    require_changed_files(result, {"recurrent_block.py"})
    try:
        workdir, _ = make_workdir(patched_dir)
        sys.path.insert(0, workdir)
        from recurrent_block import RecurrentBlock

        torch.manual_seed(17)
        block = RecurrentBlock(4, 4, depth=TRAIN_DEPTH)
        x = torch.randn(3, 4)
        checks = {}

        # One transition is the exact depth-one contract.
        checks["depth_one_exact"] = torch.equal(
            block(x, depth=1), block.transition(x)
        )

        # The configured depth must consume the state returned at every step.
        expected_train = rollout(block, x, TRAIN_DEPTH)
        checks["configured_depth_exact"] = torch.equal(
            block(x, depth=TRAIN_DEPTH), expected_train
        )

        # Do not overfit to the training depth: the same block must extrapolate.
        expected_hidden = rollout(block, x, HIDDEN_DEPTH)
        checks["hidden_depth_exact"] = torch.equal(
            block(x, depth=HIDDEN_DEPTH), expected_hidden
        )

        # A tied module has the same parameter structure at every requested depth.
        shallow = RecurrentBlock(4, 4, depth=1)
        deep = RecurrentBlock(4, 4, depth=HIDDEN_DEPTH)
        checks["parameter_count_independent_of_depth"] = (
            sum(p.numel() for p in shallow.parameters())
            == sum(p.numel() for p in deep.parameters())
            and len(list(deep.parameters())) == len(list(shallow.parameters()))
        )

        # Compare batched execution with independent examples to catch state
        # accidentally shared across the batch dimension.
        rows = [x[i : i + 1] for i in range(x.shape[0])]
        separate = torch.cat([block(row, depth=HIDDEN_DEPTH) for row in rows], dim=0)
        checks["batch_independence"] = torch.equal(
            block(x, depth=HIDDEN_DEPTH), separate
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
