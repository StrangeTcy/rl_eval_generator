"""Interface-summary solver for a recursively defined constraint grammar.

A grammar names a few module types, each with an enter port and a leave port.
Leaf types list the allowed (enter, leave) pairs. Branch types expand into a
left child and a right child, wired by three finite pair tables. The same
productions apply at every remaining depth until the leaves. A closing table,
if present, further restricts the root pair.
"""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        """Return the compact interface certificate for this grammar.

        Expected output:
            {
              "status": "sat" | "unsat",
              "realizable": {type: {depth: [[enter, leave], ...]}},
              "root_enter": label,   # sat only
              "root_leave": label,   # sat only
            }
        """
        depth = int(instance["depth"])
        modules = instance["modules"]
        tip = modules["tip"]
        tip_pairs = [list(pair) for pair in tip["pairs"]]
        realizable = {}
        for name, spec in modules.items():
            if spec["kind"] == "leaf":
                realizable[name] = {"0": [list(pair) for pair in spec["pairs"]]}
            else:
                realizable[name] = {
                    str(k): [list(pair) for pair in tip_pairs] for k in range(1, depth + 1)
                }
        root_pair = tip_pairs[0]
        return {
            "status": "sat",
            "realizable": realizable,
            "root_enter": root_pair[0],
            "root_leave": root_pair[1],
        }
