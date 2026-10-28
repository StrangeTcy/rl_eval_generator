# Block codes over a prime field

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

- `modulus`: a prime `p`. All arithmetic is modulo `p`.
- `blocks`: each block has `length` and a parity-check matrix `H`. A vector
  `v` is a local codeword iff `H v = 0` (matrix-vector product over the field).
- `glues`: overlap constraints `{left: [block, index], right: [block, index], scale}`
  requiring `visible_left[index] = scale * visible_right[index] (mod p)`.
- `parent_check`: `{vars: [[block, index], ...], row: [...], rhs: r}` requires
  the dot product of `row` with those visible symbols to equal `rhs`.
- `calibration`: per block, `codewords` are sample unpermuted local words and
  `observed` are the same probes in the presented coordinate order. In inferred
  mode, recover the coordinate permutation that maps each `codewords` entry to
  its `observed` entry.
- `representation`: `"revealed"` includes `perms`, a coordinate permutation
  per block applied **before** glue and parent checks (`visible[i] = v[perm[i]]`).
  In inferred mode `perms` is absent from the input; recover it from calibration.

A global codeword is an assignment of a vector to every block that meets every
local check, every glue, and the parent check at once. Local kernels may be
nonempty while that stacked system has no solution.

## Output

```python
{"status": "sat", "blocks": {"A": [..], "B": [..]}, "perms": {"A": [0, 1], "B": [1, 0]}}
{"status": "unsat"}
```

SAT vectors are in the **unpermuted** coordinates of each block. In inferred
mode, `perms` is required and must explain every calibration probe. A crash is
not a verdict. `solve` must be deterministic.

## Visible checks

```bash
python visible_tests.py
```

## Calibration ambiguity and corruption

Every input also contains `identification = [p, probes, observed, received]`.
This is a length-three code with check x+y+z = 0 modulo p. An unknown
permutation pi presents a word w as [w[pi[0]],w[pi[1]],w[pi[2]].
Each probe and its observed word is supplied. Some calibrations distinguish
all coordinates; others leave an exchange of two coordinates ambiguous.

Return `"identification": [admissible_permutations, syndrome, corrections]`.
List exactly all permutations consistent with all probes. The syndrome is
the sum of received coordinates modulo p. Corrections is the set of all
words obtained by subtracting that syndrome from one received coordinate,
modulo p; list each resulting word once. Do not claim a unique coordinate
label or unique correction when the observations leave several possibilities.
Order does not affect these sets.

The main block certificate must have exactly the declared number of field
coordinates in each block. Coordinate changes can permute and scale the
matrices, calibration words, and parent equation; use the supplied values.
The identification certificate is mandatory for both sat and unsat answers.
