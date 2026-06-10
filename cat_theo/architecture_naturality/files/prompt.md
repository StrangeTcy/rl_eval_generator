# Natural Transformation Between Two Model Architectures

Your task is to implement/correct a Natural Transformation `%%MODEL_CLASS%%` in `converter.py`.

In Categorical Deep Learning, mappings between different model architectures (like mapping Transformer hidden representations $F$ to RNN hidden representations $G$) are modeled as natural transformations. For a transformation to be natural, it must commute with sequence operations. That is, slicing or downsampling the sequence in the Transformer domain and then converting must equal converting and then downsampling in the RNN domain:
$$\alpha_Y \circ F(h) \equiv G(h) \circ \alpha_X$$
where $h: X \to Y$ is a sequence morphism (like pooling or slicing).

The starting implementation in `converter.py` applies a simple linear map but ignores the positional/sequence alignment of the hidden states, which violates this commutativity property. Correct the implementation so that it preserves naturality under temporal slicing.
