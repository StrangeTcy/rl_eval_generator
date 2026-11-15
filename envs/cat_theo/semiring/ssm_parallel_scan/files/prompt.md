# Parallel State-Space Scan

Your task is to correct the state composition operator `combine` in `ssm.py`.

In State-Space Models (SSMs), sequential updates can be computed in parallel using an associative prefix scan over state transitions. For this parallel scan to be mathematically equivalent to a standard sequential recurrent pass, the transition composition operator must be strictly associative:
$$(s_1 \otimes s_2) \otimes s_3 \equiv s_1 \otimes (s_2 \otimes s_3)$$

Each state `(u, M)` represents `h_next = M * h_previous + u`, where `*` is elementwise multiplication. Both tensors have matching `(..., D)` shapes: `M` contains batched diagonal transition coefficients, not dense matrices. `combine(state1, state2)` must represent applying `state1` first and `state2` second. Preserve that chronology as well as the associativity law. Associativity alone cannot distinguish chronological composition from reverse chronological composition.
