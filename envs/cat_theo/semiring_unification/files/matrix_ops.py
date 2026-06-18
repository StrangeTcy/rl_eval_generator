def generic_matmul(A: list[list], B: list[list], semiring) -> list[list]:
    """Computes matrix multiplication over an arbitrary Semiring."""
    n = len(A)
    m = len(A[0])
    k = len(B[0])
    
    out = [[semiring.zero for _ in range(k)] for _ in range(n)]
    
    for i in range(n):
        for j in range(k):
            val = semiring.zero
            for l in range(m):
                prod = semiring.mul(A[i][l], B[l][j])
                val = semiring.add(val, prod)
            out[i][j] = val
    return out
