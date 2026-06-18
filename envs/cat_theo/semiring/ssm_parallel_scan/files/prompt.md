# Parallel State-Space Scan

Your task is to correct the state composition operator `combine` in `ssm.py`.

In State-Space Models (SSMs), sequential updates can be computed in parallel using an associative prefix scan over state transitions. For this parallel scan to be mathematically equivalent to a standard sequential recurrent pass, the transition composition operator must be strictly associative:
$$(s_1 \otimes s_2) \otimes s_3 \equiv s_1 \otimes (s_2 \otimes s_3)$$

The current implementation of the `combine` method in `ssm.py` runs, but fails this associativity requirement, causing parallel scans to diverge from sequential rollouts. Fix the combination logic so that it is strictly associative.
