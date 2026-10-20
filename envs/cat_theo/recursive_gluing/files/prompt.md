# Region-network assignment

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one instance, a dict with two keys:

- `regions`: mapping from region id (string) to `{"domain": [label, ...]}`.
  Each domain is a nonempty list of distinct local state labels. Different
  regions may use different labels for states that correspond.
- `overlaps`: a list of `{"left": id, "right": id, "pairs": [[a, b], ...]}`.
  A pair `[a, b]` means local state `a` of `left` is compatible with local
  state `b` of `right`.

Region ids may be nested (`root`, `root/L`, `root/L/R`, ...). Nested ids are
part of the instance structure: overlaps can connect a region to another at
the same nesting depth, to a child, or across several levels.

## Output

Return exactly one of:

```python
{"status": "sat", "assignment": {region_id: label, ...}}
{"status": "unsat"}
```

If `status` is `"sat"`, `assignment` must give every region a label from that
region's domain, and every overlap must contain the chosen pair. If several
assignments work, any valid one is accepted, but `solve` must be deterministic:
calling it twice on the same instance returns equal results.

If no assignment exists, return `{"status": "unsat"}`. Do not treat a crash,
timeout, or parse failure as proof that nothing works.

## What "correct" means

Every region can look locally fine, and every neighbouring pair can have at
least one compatible joint state, while the whole network still has no
assignment that satisfies every overlap at once. The solver must accept the
networks that do glue together — including nested and cyclic ones — and must
reject the ones that do not.

Copying a label from one region to another is not enough: labels are local.
Transport has to follow the listed pairs.

## Visible checks

```bash
python visible_tests.py
```
