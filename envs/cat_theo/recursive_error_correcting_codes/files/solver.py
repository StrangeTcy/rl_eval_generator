"""Weak baseline: local zeros, ignore parent parity."""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        blocks = {}
        p = int(instance["modulus"])
        for name, spec in instance["blocks"].items():
            vec = [0] * int(spec["length"])
            if spec.get("H") == [[1, 1]] and spec["length"] == 2:
                vec = [1, (p - 1) % p]
            blocks[name] = vec
        return {"status": "sat", "blocks": blocks}
