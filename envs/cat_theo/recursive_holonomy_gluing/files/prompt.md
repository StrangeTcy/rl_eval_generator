# Finite maps on nested modules

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one instance:

- `family`: `"multiplicative"`, `"affine"`, or `"permutation"`.
- `modulus`: a prime `p`.
- `domain`: the allowed states. Multiplicative uses `{1, ..., p-1}`;
  affine uses `{0, ..., p-1}`; permutation uses `{0, ..., n-1}`.
- `modules`: each module has ports `in` and `out`. A `node` has a `child`
  whose in-to-out map is used as a factor of the parent map.
- `root`, `depth`, `cycle`: `cycle` is a list of map names. Apply them
  **in listed order, first name first**.
- `calibration`: for each named map, a list of `[x, y]` pairs that the map
  must send `x` to `y`.
- `representation`: `"revealed"` includes a `maps` field with the maps
  written out; `"inferred"` and `"explicit"` follow the same field rules
  (`explicit` also includes `expanded`, the same maps as a flat list).

Map families (exact):

- multiplicative: `y = (q * x) mod p` with `q` in `{1, ..., p-1}`.
- affine: `y = (a * x + b) mod p` with `a` in `{1, ..., p-1}`.
- permutation: `y = image[x]` for a listed bijection `image`.

A state `s` in `domain` is **compatible** when applying every map in `cycle`
in order returns `s`.

## Output

```python
{"status": "sat", "state": s, "maps": {"leaf": {...}, ...}}
{"status": "unsat"}
```

If `representation` is `"inferred"`, SAT answers must include `maps` that
match every calibration pair. A crash or parse failure is not a verdict.
`solve` must be deterministic.

## Visible checks

```bash
python visible_tests.py
```
