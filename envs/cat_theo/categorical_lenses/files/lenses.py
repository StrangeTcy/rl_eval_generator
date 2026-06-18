class %%MODEL_CLASS%%:
    def view(self, s: tuple[float, float]) -> float:
        return s[0]

    def update(self, s: tuple[float, float], a: float) -> tuple[float, float]:
        # BUG: Naive update that hardcodes the un-updated coordinate to 0.0.
        # This violates the Get-Put identity law: update(s, view(s)) must equal s.
        return (a, 0.0)
