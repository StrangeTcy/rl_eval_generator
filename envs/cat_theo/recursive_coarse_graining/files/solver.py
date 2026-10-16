"""Weak baseline: first region's table, claim a fixed point."""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        name = next(iter(instance["regions"]))
        w = instance["regions"][name]["weights"]
        table = [
            [int(w[0][0][0]) + int(w[0][1][0]), int(w[0][0][1]) + int(w[0][1][1])],
            [int(w[1][0][0]) + int(w[1][1][0]), int(w[1][0][1]) + int(w[1][1][1])],
        ]
        return {"table": table, "fixed": True}
