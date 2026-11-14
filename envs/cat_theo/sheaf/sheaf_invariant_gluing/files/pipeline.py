import math

class %%MODEL_CLASS%%:
    def normalize(self, x: float) -> float:
        # Maps input x to [-1.0, 1.0] using hyperbolic tangent
        return math.tanh(x)

    def discretize(self, x: float) -> int:
        # Maps x in [-1.0, 1.0] to a discrete bucket [0, 99].
        bucket = int((x + 1.0) / 2.0 * 100)
        if bucket < 0 or bucket >= 100:
            raise IndexError(f"Bucket index {bucket} is out of bounds!")
        return bucket

    def compose_pipeline(self, x: float) -> int:
        norm_x = self.normalize(x)
        return self.discretize(norm_x)
