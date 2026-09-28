# Adaptive halting evaluation

Repair `halting.py` so `AdaptiveHaltingBlock` applies a tied transition for the
number of steps requested by each individual batch element. Once a row reaches
its `halt_after` count, its state must remain frozen while other rows continue.

The largest ordinary depth is `%%TRAIN_DEPTH%%`; hidden evaluation includes
`%%HIDDEN_DEPTH%%`. `%%CLUE%%`

Do not normalize halting probabilities across batch elements and do not use one
scalar active flag for all examples. `%%IMPLEMENTATION_NOTE%%`
