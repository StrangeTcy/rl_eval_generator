#!/usr/bin/env python3
"""Hidden checks for recurrent autograd credit assignment."""
from __future__ import annotations

import sys

import torch

from judge_lib import (
    base_result,
    emit,
    make_workdir,
    score_from_checks,
    require_changed_files,
    set_failure,
    validate_submission,
)

TRAIN_DEPTH = %%TRAIN_DEPTH%%
HIDDEN_DEPTH = %%HIDDEN_DEPTH%%
TOTAL_CHECKS = %%SCORING_TOTAL_CHECKS%%


def trusted_forward(block, x, depth):
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
        from recurrent_block import CreditBlock

        torch.manual_seed(31)
        block = CreditBlock(4, 4, depth=TRAIN_DEPTH)
        with torch.no_grad():
            block.transition.weight.mul_(0.1)
            block.transition.bias.mul_(0.1)
        reference_block = CreditBlock(4, 4, depth=TRAIN_DEPTH)
        reference_block.load_state_dict(block.state_dict())
        x_a = torch.randn(3, 4, requires_grad=True)
        x_b = x_a.detach().clone().requires_grad_(True)
        target = torch.randn(3, 4)
        checks = {}

        loss_a = (block(x_a, depth=TRAIN_DEPTH) - target).square().mean()
        loss_b = (trusted_forward(reference_block, x_b, TRAIN_DEPTH) - target).square().mean()
        loss_a.backward()
        loss_b.backward()
        input_grad_ok = x_a.grad is not None and x_b.grad is not None and torch.allclose(
            x_a.grad, x_b.grad, atol=1e-6, rtol=1e-5
        )
        param_grad_ok = all(
            left.grad is not None
            and right.grad is not None
            and torch.allclose(left.grad, right.grad, atol=1e-6, rtol=1e-5)
            for left, right in zip(block.parameters(), reference_block.parameters())
        )
        checks["input_gradient_equivalence"] = input_grad_ok
        checks["parameter_gradient_equivalence"] = param_grad_ok

        # Held-out depth should still produce finite values and gradients.
        hidden_x = torch.randn(2, 4, requires_grad=True)
        hidden_out = block(hidden_x, depth=HIDDEN_DEPTH)
        hidden_out.square().mean().backward()
        checks["finite_larger_depth_gradients"] = (
            torch.isfinite(hidden_out).all().item()
            and hidden_x.grad is not None
            and torch.isfinite(hidden_x.grad).all().item()
            and all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in block.parameters())
        )

        # A deterministic optimization step should lower a simple trusted loss.
        opt_block = CreditBlock(4, 4, depth=min(TRAIN_DEPTH, 8))
        with torch.no_grad():
            opt_block.transition.weight.mul_(0.1)
            opt_block.transition.bias.zero_()
        opt = torch.optim.SGD(opt_block.parameters(), lr=1e-3)
        opt_x = torch.randn(4, 4)
        before = opt_block(opt_x).square().mean()
        opt.zero_grad()
        before.backward()
        opt.step()
        after = opt_block(opt_x).square().mean()
        checks["optimization_reduces_trusted_loss"] = bool(after.item() < before.item())

        shallow = CreditBlock(4, 4, depth=1)
        deep = CreditBlock(4, 4, depth=HIDDEN_DEPTH)
        checks["no_depth_parameter_duplication"] = (
            sum(p.numel() for p in shallow.parameters())
            == sum(p.numel() for p in deep.parameters())
            and len(list(shallow.parameters())) == len(list(deep.parameters()))
        )

        score_from_checks(result, checks, TOTAL_CHECKS)
    except Exception as exc:
        set_failure(result, "RUNTIME_ERROR", str(exc))
        result["score"] = 0.0
    emit(result)


if __name__ == "__main__":
    main()
