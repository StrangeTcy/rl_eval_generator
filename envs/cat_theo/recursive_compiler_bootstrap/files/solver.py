"""Weak baseline: trust the claimed decoder."""


class %%MODEL_CLASS%%:
    def solve(self, instance):
        return {"equivalent": True, "encodings": instance.get("encodings") or {}}
