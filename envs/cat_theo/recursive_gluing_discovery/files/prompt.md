# Chart assembly from a gadget and partial observations

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one instance:

- `regions`: mapping from region id to
  `{"domain": [label, ...], "cycle": [label, ...]}`.
  `cycle` is a rotation of that region's domain (each label once). It is
  local structure on that region, not a global numbering.
- `overlaps`: list of `{"left": id, "right": id, "pairs": [[a, b], ...]}`.
  A pair means those two local states have been observed to be compatible.
  `pairs` may be empty: the two regions still interact, but no table is given.
- `copies`: list of `{"I": id, "L": id, "R": id}` naming recursively nested
  copies of the same three-role gadget, with different local labels.
- `gadget`: region id of the root copy's interface. Overlaps incident to the
  root copy's tree edges list a complete set of compatible pairs.

Region ids nest (`root`, `root/L`, `root/L/R`, ...).

## Output

Return exactly one of:

```python
{"status": "sat", "assignment": {region_id: label, ...}}
{"status": "unsat"}
```

If `status` is `"sat"`, every region must get a label from its domain, and
the assignment must be consistent with **every** interaction between regions
that the instance declares — including overlaps whose `pairs` list is empty.
If several assignments work, any valid one is accepted, but `solve` must be
deterministic.

If no assignment exists, return `{"status": "unsat"}`. A crash, timeout, or
parse failure is not evidence that none exists.

## What "correct" means

A copy of the gadget can look locally fine, and every listed pair can hold,
while the assembled network still has no global assignment. Copying a gadget
label onto a nested copy is not enough: names are local. Overlaps with no
listed pairs still constrain the assembly.

## Visible checks

```bash
python visible_tests.py
```
