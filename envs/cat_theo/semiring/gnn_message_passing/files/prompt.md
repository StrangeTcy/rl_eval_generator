# Permutation Equivariant Message Passing

Your task is to complete the graph message-passing layer `%%MODEL_CLASS%%` in `gnn.py`.

To be structurally sound, a Graph Neural Network (GNN) aggregation layer must be strictly **permutation equivariant**. That is, permuting the input graph's node order must result in an identically permuted output representation:
$$f(P \cdot A \cdot P^T, P \cdot X) \equiv P \cdot f(A, X)$$
where $P$ is any permutation matrix, $A$ is the graph adjacency matrix, and $X$ is the input node feature matrix.

Implement the exact aggregation operator `forward(A, X) = A @ self.proj(X)`, using the supplied learned projection. An edge weight multiplies the projected source feature. Include no residual or implicit self-loop; self-loops contribute only when present in `A`. The output must also satisfy the permutation law above.
