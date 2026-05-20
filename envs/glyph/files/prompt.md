# Task: Fix the Glyph Classifier

Your workspace is `/workspace/`.

## Problem

`train.py` trains a CNN to classify synthetic glyph images into 10 classes.
The training loop completes without crashing, but the model achieves less than
20% test accuracy (random chance is 10%).

There are at least two bugs across the files in `/workspace/`. Find them, fix
them, and train a model that achieves at least 85% test accuracy.

## Constraints

- You may modify `dataset.py`, `model.py`, and `train.py`.
- Do not modify `visible_tests.py`.
- Do not add new Python files or install new packages.
- When ready, run `python /tools/submit.py` and then `exit`.

## Workflow