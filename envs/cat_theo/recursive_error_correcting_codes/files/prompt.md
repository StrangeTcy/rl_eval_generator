# Block codes over a prime field

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

- `modulus`: a prime `p`. All arithmetic is modulo `p`.
- `blocks`: each block has `length` and a parity-check matrix `H`. A vector
  `v` is a local codeword iff `H v = 0` (matrix-vector product over the field).
- `glues`: each glue `{left: [block, index], right: [block, index], scale}`
  requires `visible_left[index] = scale * visible_right[index] (mod p)`.
- `parent_check`: `{vars: [[block, index], ...], row: [...], rhs: r}` requires
  the dot product of `row` with those visible symbols to equal `rhs`.
- `calibration`: sample local codewords per block.
- `representation`: `"revealed"` includes `perms`, a coordinate permutation
  per block applied **before** glue and parent checks (`visible[i] = v[perm[i]]`).
  If `perms` is absent, treat each perm as the identity.

A global codeword is an assignment of a vector to every block that meets every
local check, every glue, and the parent check at once. Local kernels may be
nonempty while that stacked system has no solution.

## Output

```python
{"status": "sat", "blocks": {"A": [..], "B": [..]}}
{"status": "unsat"}
```

SAT vectors are in the **unpermuted** coordinates of each block. A crash is
not a verdict. `solve` must be deterministic.

## Visible checks

```bash
python visible_tests.py
```
