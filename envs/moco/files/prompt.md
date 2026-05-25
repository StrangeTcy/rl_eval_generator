# Task: Fix Representation Collapse in Self-Supervised Learning

Your workspace is `/workspace/`.

## Problem

`train.py` trains a MoCo-style contrastive model. The loss decreases smoothly
and the script exits without error. Running `eval.py` shows the linear probe
accuracy is near chance (~25% on 4 classes). The representations have collapsed.

There are at least two bugs split across the model and queue update code. Fix
them so the linear probe reaches at least 85% accuracy.
%%QUEUE_HINT%%

## Files

| File              | Purpose                                       |
|------------------|-----------------------------------------------|
| `%%MODEL_FILE%%` | The model — **the only file you should modify** |
| `queue_ops.py`   | Queue update helper — may need modification   |
| `dataset.py`     | Data generation (do not modify)               |
| `train.py`       | Training loop (do not modify)                 |
| `eval.py`        | Linear probe evaluation (do not modify)       |
| `visible_tests.py` | Tests you can run freely                    |

## Workflow