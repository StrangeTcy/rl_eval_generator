# Nested tile routes

Implement `%%MODEL_CLASS%%.solve` in `%%MODEL_FILE%%`.

## Input

`solve` receives one maze grammar:

- `root`: name of the outermost tile type.
- `depth`: remaining nesting depth at the root (positive integer).
- `tiles`: mapping from tile type to:
  - `rooms`: local room names (names are local to the type).
  - `entrance`, `exit`: room names.
  - `edges`: list of `{"from": room, "to": room, "flip": 0|1}`.
    Walking that corridor XOR-s the walker's orientation bit with `flip`.
  - `shafts`: list of `{"from": room, "return": room, "child": type, "flip": 0|1}`.
    From `from`, the walker may **descend** into a child copy. The child type
    is `child` when remaining depth is 1. When remaining depth is at least 2,
    the child type is `nesting["deeper"]`. Descending XOR-s orientation with `flip`. Completing the child
    (standing at the child's `exit`) allows **ascend**, which returns to
    `return` in the parent.
- `start_orientation`, `goal_orientation`: bits in `{0, 1}`.
- `nesting`: `{"deeper": tile_type}` naming the child type used when remaining
  depth is at least 2. May be empty when no deeper copy exists.

If a tile lists shafts, the root copy of that tile keeps its `exit` **sealed**
until the walker has descended into a child and ascended back at least once.

Each directed edge in a given nested copy may be used at most once.

## Output

```python
{"status": "sat", "steps": [step, ...]}
{"status": "unsat"}
```

Each step is one of `{"op": "move", "to": room}`,
`{"op": "descend", "child": type}`, `{"op": "ascend"}`. `child` is the tile
type actually entered. A sat walk starts at the root entrance with
`start_orientation` and must finish at the root exit with `goal_orientation`,
stack empty (not inside a child). A crash, timeout, or parse failure is not
evidence that no walk exists. `solve` must be deterministic.

## What "correct" means

Every child tile can have a walk from its entrance to its exit while no walk
meets the root orientation and sealing rules. Copying a child walk into a
different tile type is not enough: room names are local, and `flip` bits
compose along the walk.

## Visible checks

```bash
python visible_tests.py
```

## Mixed tile compositions

A nesting description may include `by_depth`, mapping the remaining-depth
integer as a string to a tile name. When remaining depth exceeds one, use
that tile instead of `deeper` if a by_depth entry exists. At remaining depth
one, the shaft's named child is used. All flip, exit-sealing, return, and
edge-use rules still apply. Reaching or clearing a child does not create a
fresh copy of an already used parent edge. Full-state search is permitted.
