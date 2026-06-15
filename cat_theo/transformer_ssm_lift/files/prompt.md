# Stateful Attention-to-Recurrence Lift

Your task is to correct the state lifting function `%%MODEL_CLASS%%` in `lifter.py`.

In sequential sequence modeling, converting history-dependent self-attention key/values into a recurrent state matrix represents a state-space transformation. For the transformation to be correct and lossless, reading the lifted recurrent state must produce the exact same attention outputs as the original sequence history under composition.

The starting implementation in `lifter.py` runs, but performs a lossy transformation that violates this stateful equivalence. Correct the lifting function so that the state conversion is mathematically correct and lossless.
