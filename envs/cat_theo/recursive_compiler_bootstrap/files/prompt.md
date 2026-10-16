# Source, bytecode, and encodings

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Languages

Source expressions, evaluated modulo `modulus`:

- an integer `n`
- `["add", left, right]`

Bytecode, stack machine, same modulus:

- `["push", n]` pushes `n`
- `["add"]` replaces the top two values `a, b` with `(a + b) mod modulus`
- `["halt"]` returns the top of stack

A compiler from source is: integers become `push`; `add` concatenates the
compiled children and then `add`. A trailing `halt` is added.

An **encoding** assigns each of `push`, `add`, `halt` a distinct opcode id
in `{0,1,2}`. Encoded programs use those ids in the first slot of each
instruction. A **decoder** is the inverse map id → name.

## Input

- `modulus`, `programs`: the finite set of source programs the claim is about.
- `stages`: ordered path. `"compile"` then optional `"recode"` with a
  permutation of opcode ids.
- `claimed_decoder`: map from opcode id to name for the **last** stage's
  encoding.
- `calibration`: a few `{source, bytes}` pairs produced by that last encoding.
- `representation`: `"revealed"` also lists `encodings`.

The claim is: for every program in `programs`, evaluating the source equals
evaluating the bytecode obtained by compiling, encoding with the last-stage
encoding, and decoding with `claimed_decoder`.

Each stage may still be correct **relative to its own encoding** even if the
claimed decoder for the whole path is not.

## Output

```python
{"equivalent": True, "encodings": {...}}
{"equivalent": False, "counterexample": {"source": expr, "source_value": int, "decoded_value": int}}
```

`equivalent` must be a Boolean. If you claim false, cite a program from the
instance (or any well-formed source) that actually disagrees under the claimed
decoder. `solve` must be deterministic.

## Visible checks

```bash
python visible_tests.py
```
