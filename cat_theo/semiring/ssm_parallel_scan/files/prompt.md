# Associative Scan in State-Space Models (SSM)

Your task is to implement the associative scan binary operator in `ssm.py`.

In State-Space Models like Mamba, sequence updates are linear recurrences:
$$h_t = A_t h_{t-1} + B_t x_t$$

To run this recurrence in parallel on GPUs, the state updates are computed as an associative prefix scan over a monoid. The binary operator $\otimes$ must be strictly associative:
$$(u_1, M_1) \otimes (u_2, M_2) = (M_2 u_1 + u_2, M_2 M_1)$$

If the operator is not associative (for example, if you swap the multiplication order or fail to scale the state correctly), the parallel scan output will completely diverge from the standard sequential scan. Correct the operator in `ssm.py` so that parallel scan commutes perfectly with sequential scan.
