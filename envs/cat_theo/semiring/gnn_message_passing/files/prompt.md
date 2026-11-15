# Permutation Equivariant Message Passing

Your task is to complete the graph message-passing layer `%%MODEL_CLASS%%` in `gnn.py`.

The required operator is `forward(A, X) = A @ self.proj(X)`. Adjacency entries are supplied weights; do not normalize them or add self-loops or a residual term. Self-contributions occur only when the supplied adjacency has a diagonal entry. Preserve `self.proj` as the learned feature projection. Inputs have shapes `(N, N)` and `(N, in_features)`; output shape is `(N, out_features)`.

To be structurally sound, a Graph Neural Network (GNN) aggregation layer must be strictly **permutation equivariant**. That is, permuting the input graph's node order must result in an identically permuted output representation:
$$f(P \cdot A \cdot P^T, P \cdot X) \equiv P \cdot f(A, X)$$
where $P$ is any permutation matrix, $A$ is the graph adjacency matrix, and $X$ is the input node feature matrix.

The current implementation in `gnn.py` runs, but fails to satisfy this equivariance property. Correct the implementation of `forward()` to ensure it behaves equivariantly for any arbitrary node permutation.
