# Task: Fix BatchNorm Corruption under Gradient Accumulation

Your workspace is `/workspace/`.

## Problem

`train.py` trains a ResNet on CIFAR using gradient accumulation. The loss
decreases normally and the script exits without error. However, test accuracy
plateaus well below what the architecture is capable of.

There is a bug in the interaction between gradient accumulation and BatchNorm.
Find it and fix it.

Any approach that produces a model whose BatchNorm (or replacement
normalization) statistics are correct under accumulation is acceptable. For
example, you might scale BatchNorm momentum for the accumulation schedule, avoid
updating running statistics on every micro-batch and update them on a
representative batch, recalibrate the running statistics after training, or
replace BatchNorm with a normalization that does not depend on the micro-batch
statistics. The grader scores behavior, not a specific patch shape.

## Constraints

- You may modify `model.py` and `train.py`.
- Do not change the optimizer type, base learning rate, or BATCH_SIZE constant.
- Do not add new Python dependencies.
- When ready, run `python /tools/submit.py` and then `exit`.

## Workflow