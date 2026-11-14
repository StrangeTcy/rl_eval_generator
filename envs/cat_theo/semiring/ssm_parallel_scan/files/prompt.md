# Parallel State-Space Scan

Your task is to correct the state composition operator `combine` in `ssm.py`.

In State-Space Models (SSMs), sequential updates can be computed in parallel using an associative prefix scan over state transitions. For this parallel scan to be mathematically equivalent to a standard sequential recurrent pass, the transition composition operator must be strictly associative:
$$(s_1 \otimes s_2) \otimes s_3 \equiv s_1 \otimes (s_2 \otimes s_3)$$

Each state `(u, M)` represents the affine update `h -> M * h + u`. `M` contains batched diagonal coefficients with the same shape as `u`; multiplication is elementwise. `combine(state1, state2)` must represent applying `state1` first, then `state2`.

Implement both chronological equivalence and associativity. Associativity alone does not determine chronology: composing updates in reverse order is also associative but gives a different recurrent pass.
