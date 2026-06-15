# Algebraic Aggregation in GNNs

Your task is to implement an equivariant neighborhood aggregator in `gnn.py`.

In Geometric Deep Learning, graph message-passing layers are category-theoretic functors from the category of Graphs to the category of Vector Spaces. For a Graph Neural Network (GNN) layer to be correct, it must be **permutation equivariant**:
$$f_{\text{GNN}}(P \cdot A \cdot P^T, P \cdot X) \equiv P \cdot f_{\text{GNN}}(A, X)$$
for any permutation matrix $P$, adjacency matrix $A$, and node features $X$.

To guarantee scale and permutation invariance, neighborhood aggregation must satisfy the identity and distributivity properties of a Semiring.

The starting implementation in `gnn.py` uses a naive aggregation loop that has a hardcoded indexing bias (representing a coordinate trap), which breaks permutation equivariance when nodes are permuted. Fix the neighborhood aggregator to use a mathematically robust, permutable reduce operation (like `sum` or `max`) across the neighborhood adjacency.
