# Task: Fix Representation Collapse in Self-Supervised Learning

Your workspace is `/workspace/`.

## Problem

`train.py` trains a MoCo-style contrastive model. The loss decreases smoothly
and the script exits without error. Running `eval.py` shows the linear probe
accuracy is near chance (~25% on 4 classes). The representations have collapsed.

There are at least two bugs split across the model and queue update code. Fix
them so the linear probe reaches at least 85% accuracy.
%%QUEUE_HINT%%

The contrastive objective uses unit-length projected queries and keys. Each
positive and negative dot product is divided by the scalar temperature exactly
once. Stored queue columns are unit-length keys, and FIFO insertion preserves
arrival order across the queue boundary. Preserve `encoder_q`, `encoder_k`,
`proj_q`, `proj_k`, and the `%%QUEUE_ATTR%%` buffer interface. Behavioral checks
and held-out accuracy determine acceptance; no particular set of edited files
is required.

## Files

| File              | Purpose                                       |
|------------------|-----------------------------------------------|
| `%%MODEL_FILE%%` | The model — **one of the files you should modify** |
| `queue_ops.py`   | Queue update helper — may need modification   |
| `dataset.py`     | Data generation (do not modify)               |
| `train.py`       | Training loop (do not modify)                 |
| `eval.py`        | Linear probe evaluation (do not modify)       |
| `visible_tests.py` | Tests you can run freely                    |

## Workflow
