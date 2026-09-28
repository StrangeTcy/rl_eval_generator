# Recurrent gradient-credit evaluation

Repair `recurrent_block.py` so `CreditBlock` unrolls a tied transition without
breaking autograd. Gradients must flow from the final output through every
transition to both the input and shared parameters.

The ordinary depth is `%%TRAIN_DEPTH%%`, with a held-out depth of
`%%HIDDEN_DEPTH%%`. `%%CLUE%%`

Do not replace intermediate states with detached or freshly copied tensors, and
do not create one parameter set per depth. `%%IMPLEMENTATION_NOTE%%`
