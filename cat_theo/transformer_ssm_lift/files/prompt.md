# Transformer-to-SSM State Lift

Your task is to implement a state lifting morphism `%%MODEL_CLASS%%` in `lifter.py`.

In sequential model architectures, mapping historical context from self-attention key/value matrices to state-space models (like Mamba) represents a state isomorphism. For a lift map $L$ to preserve stateful transition symmetries under shift operations:
$$L(T_t(X)) \equiv T'_t(L(X))$$

The starting code in `lifter.py` implements a projection that collapses temporal elements, discarding history-dependent features and causing information loss. Correct the lifting function so that the state transformation forms a lossless representation across timesteps.
