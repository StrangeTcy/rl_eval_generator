class %%MODEL_CLASS%%:
    def view(self, s: tuple[float, float]) -> float:
        return s[0]

    def update(self, s: tuple[float, float], a: float) -> tuple[float, float]:
        return (a, 0.0)
