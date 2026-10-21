"""Weak baseline: nonempty domain => sat, ignore the cycle."""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        domain = instance["domain"]
        maps = instance.get("maps") or {}
        return {"status": "sat", "state": int(domain[0]), "maps": maps}
