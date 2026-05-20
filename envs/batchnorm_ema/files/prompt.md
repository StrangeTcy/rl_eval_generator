# Task: Fix BatchNorm Corruption under Gradient Accumulation

Your workspace is `/workspace/`.

## Problem

`train.py` trains a ResNet on CIFAR using gradient accumulation. The loss
decreases normally and the script exits without error. However, test accuracy
plateaus well below what the architecture is capable of.

There is a bug in the interaction between gradient accumulation and BatchNorm.
Find it and fix it.

## Constraints

- You may modify `model.py` and `train.py`.
- Do not change the optimizer type, base learning rate, or BATCH_SIZE constant.
- Do not add new Python dependencies.
- When ready, run `python /tools/submit.py` and then `exit`.

## Workflow