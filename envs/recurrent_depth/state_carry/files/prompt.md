# Recurrent state-carry evaluation

Repair `recurrent_block.py` so `RecurrentBlock` applies one tied transition for
`depth` steps. The output of step t must be the input state for step t plus one;
do not repeatedly feed the original input after the first step.

The default training depth is `%%TRAIN_DEPTH%%`; evaluation may request the
unseen depth `%%HIDDEN_DEPTH%%`. `%%CLUE%%`

Preserve normal PyTorch batching. `%%IMPLEMENTATION_NOTE%%`
Only edit the requested implementation file, then run `python visible_tests.py`.
